from typing import Any, Optional, cast, get_args

from posthog.test.base import APIBaseTest, BaseTest
from unittest.mock import patch

from django.test import SimpleTestCase

from parameterized import parameterized
from prometheus_client import REGISTRY
from rest_framework.exceptions import Throttled, ValidationError

from posthog.hogql.database.data_catalog_metrics import CatalogSurface
from posthog.hogql.errors import ExposedHogQLError, QueryError

from posthog.clickhouse.client.limit import ConcurrencyLimitExceeded
from posthog.clickhouse.query_tagging import Product, get_query_tags
from posthog.errors import ExposedCHQueryError
from posthog.exceptions import ClickHouseAtCapacity, ClickHouseQueryTimeOut

from products.data_catalog.backend.logic import relationships
from products.data_catalog.backend.logic.exceptions import MetricHasNoDefinition
from products.data_catalog.backend.logic.execution import run_metric
from products.data_catalog.backend.logic.metrics import upsert_metric
from products.data_catalog.backend.logic.relationships import accept_proposal, propose_relationship
from products.data_catalog.backend.metrics import DefinitionKindLabel, MetricRunOutcome, RelationshipProbeOutcome

_RUNS_METRIC = "posthog_data_catalog_metric_runs_total"
_DURATION_COUNT_METRIC = "posthog_data_catalog_metric_run_duration_seconds_count"
_PROBE_METRIC = "posthog_data_catalog_relationship_probe_total"
_READS_METRIC = "posthog_data_catalog_reads_total"
_READ_FAILURES_METRIC = "posthog_data_catalog_read_failures_total"

_KINDS = get_args(DefinitionKindLabel)
_OUTCOMES = get_args(MetricRunOutcome)
_PROBE_OUTCOMES = get_args(RelationshipProbeOutcome)
_SURFACES = get_args(CatalogSurface)

_PROCESS_QUERY = "products.data_catalog.backend.logic.execution.process_query_dict"

# ClickHouse error codes. Every one is user_safe, so all four surface as ExposedCHQueryError, but
# they classify differently: a missing table is the definition's problem, a timeout is a cost
# guardrail, and an unreadable S3 file is ours.
_UNKNOWN_TABLE_CODE = 60
_ILLEGAL_TYPE_CODE = 43
_TIMEOUT_EXCEEDED_CODE = 159
_S3_ERROR_CODE = 499

_HOGQL = {"kind": "HogQLQuery", "query": "select count() as c from events"}
_EVENTS_NODE = {"kind": "EventsNode", "event": "purchase"}
_MARKDOWN = {"kind": "MarkdownDefinition", "markdown": "1. Count activated users."}
_OK_PAYLOAD: dict[str, Any] = {"results": [[1]], "hogql": "SELECT 1"}
_ASYNC_PAYLOAD: dict[str, Any] = {"results": None, "query_status": {"id": "abc", "complete": False}}

_JOIN: dict[str, Any] = {
    "source_table_name": "events",
    "source_table_key": "distinct_id",
    "joining_table_name": "persons",
    "joining_table_key": "id",
    "field_name": "linked_person",
}


def _sample(name: str, labels: dict[str, str]) -> float:
    return REGISTRY.get_sample_value(name, labels) or 0.0


def _run_outcomes() -> dict[tuple[str, str], float]:
    return {
        (kind, outcome): _sample(_RUNS_METRIC, {"definition_kind": kind, "outcome": outcome})
        for kind in _KINDS
        for outcome in _OUTCOMES
    }


def _durations() -> dict[str, float]:
    return {kind: _sample(_DURATION_COUNT_METRIC, {"kind": kind}) for kind in _KINDS}


def _probe_outcomes() -> dict[str, float]:
    return {outcome: _sample(_PROBE_METRIC, {"outcome": outcome}) for outcome in _PROBE_OUTCOMES}


def _delta(before: dict, after: dict) -> dict:
    return {key: after[key] - value for key, value in before.items() if after[key] != value}


class TestPreCreatedSeries(SimpleTestCase):
    def test_every_alert_relevant_label_combination_exists_at_import(self) -> None:
        for kind in _KINDS:
            assert REGISTRY.get_sample_value(_DURATION_COUNT_METRIC, {"kind": kind}) is not None, kind
            for outcome in _OUTCOMES:
                assert (
                    REGISTRY.get_sample_value(_RUNS_METRIC, {"definition_kind": kind, "outcome": outcome}) is not None
                ), f"{kind}/{outcome}"
        for probe_outcome in _PROBE_OUTCOMES:
            assert REGISTRY.get_sample_value(_PROBE_METRIC, {"outcome": probe_outcome}) is not None, probe_outcome
        for surface in _SURFACES:
            assert REGISTRY.get_sample_value(_READS_METRIC, {"surface": surface}) is not None, surface
            assert REGISTRY.get_sample_value(_READ_FAILURES_METRIC, {"surface": surface}) is not None, surface


class TestMetricRunOutcomes(APIBaseTest):
    @parameterized.expand(
        [
            ("blocking_success", _HOGQL, {"return_value": dict(_OK_PAYLOAD)}, {}, None, "hogql", "success"),
            ("node_success", _EVENTS_NODE, {"return_value": dict(_OK_PAYLOAD)}, {}, None, "node", "success"),
            ("markdown_success", _MARKDOWN, {"return_value": dict(_OK_PAYLOAD)}, {}, None, "markdown", "success"),
            (
                "async_enqueue",
                _HOGQL,
                {"return_value": dict(_ASYNC_PAYLOAD)},
                {"refresh": "async"},
                None,
                "hogql",
                "async_enqueued",
            ),
            (
                "definition_error_hogql",
                _HOGQL,
                {"side_effect": ExposedHogQLError("no such table")},
                {},
                ValidationError,
                "hogql",
                "definition_error",
            ),
            (
                "definition_error_clickhouse",
                _HOGQL,
                {"side_effect": ExposedCHQueryError("Unknown table", code=_UNKNOWN_TABLE_CODE)},
                {},
                ValidationError,
                "hogql",
                "definition_error",
            ),
            (
                "invalid_query",
                _HOGQL,
                {"return_value": {"results": None, "error": "1 validation error"}},
                {},
                ValidationError,
                "hogql",
                "invalid_query",
            ),
            ("rejected_no_definition", None, {}, {}, MetricHasNoDefinition, "none", "rejected"),
            ("rejected_date_override", _HOGQL, {}, {"date_from": "-7d"}, ValidationError, "hogql", "rejected"),
            (
                "rejected_safeguard",
                _HOGQL,
                {"side_effect": ValidationError("that construct is not allowed")},
                {},
                ValidationError,
                "hogql",
                "rejected",
            ),
            (
                "concurrency_limited",
                _HOGQL,
                {"side_effect": ConcurrencyLimitExceeded("too many")},
                {},
                Throttled,
                "hogql",
                "concurrency_limited",
            ),
            (
                "query_performance_timeout",
                _HOGQL,
                {"side_effect": ClickHouseQueryTimeOut()},
                {},
                ClickHouseQueryTimeOut,
                "hogql",
                "query_performance",
            ),
            (
                "query_performance_exposed_guardrail",
                _HOGQL,
                {"side_effect": ExposedCHQueryError("timeout exceeded", code=_TIMEOUT_EXCEEDED_CODE)},
                {},
                ValidationError,
                "hogql",
                "query_performance",
            ),
            (
                "capacity",
                _HOGQL,
                {"side_effect": ClickHouseAtCapacity()},
                {},
                ClickHouseAtCapacity,
                "hogql",
                "capacity",
            ),
            (
                "internal_error_operational_clickhouse",
                _HOGQL,
                {"side_effect": ExposedCHQueryError("S3 file changed during read", code=_S3_ERROR_CODE)},
                {},
                ValidationError,
                "hogql",
                "internal_error",
            ),
            (
                "internal_error",
                _HOGQL,
                {"side_effect": RuntimeError("engine bug")},
                {},
                RuntimeError,
                "hogql",
                "internal_error",
            ),
        ]
    )
    def test_run_records_exactly_one_outcome(
        self,
        _name: str,
        definition: Optional[dict],
        patch_kwargs: dict,
        run_kwargs: dict,
        expected_error: Optional[type[Exception]],
        expected_kind: str,
        expected_outcome: str,
    ) -> None:
        metric = upsert_metric(team=self.team, user=self.user, name="mrr", description="d", definition=definition)
        outcomes_before, durations_before = _run_outcomes(), _durations()

        with patch(_PROCESS_QUERY, **patch_kwargs):
            if expected_error is not None:
                with self.assertRaises(expected_error):
                    run_metric(team=self.team, metric=metric, user=self.user, **run_kwargs)
            else:
                run_metric(team=self.team, metric=metric, user=self.user, **run_kwargs)

        assert _delta(outcomes_before, _run_outcomes()) == {(expected_kind, expected_outcome): 1.0}
        timed = expected_outcome == "success" and expected_kind != "markdown"
        assert _delta(durations_before, _durations()) == ({expected_kind: 1.0} if timed else {})


class TestRelationshipProbeOutcomes(BaseTest):
    def _propose(self):
        return propose_relationship(team=self.team, user=self.user, **_JOIN)

    @parameterized.expand(
        [
            ("ok", None, None, "ok"),
            ("join_invalid_hogql", QueryError("no such column"), ValidationError, "join_invalid"),
            (
                "join_invalid_clickhouse",
                ExposedCHQueryError("Illegal types of arguments", code=_ILLEGAL_TYPE_CODE),
                ValidationError,
                "join_invalid",
            ),
            ("query_performance", ClickHouseQueryTimeOut(), ValidationError, "query_performance"),
            ("capacity", ClickHouseAtCapacity(), ValidationError, "capacity"),
            ("error", RuntimeError("probe infrastructure down"), ValidationError, "error"),
        ]
    )
    def test_probe_records_its_outcome(
        self,
        _name: str,
        probe_error: Optional[Exception],
        expected_error: Optional[type[Exception]],
        expected_outcome: str,
    ) -> None:
        proposal = self._propose()
        before = _probe_outcomes()

        with patch.object(relationships, "execute_hogql_query", side_effect=probe_error):
            if expected_error is not None:
                with self.assertRaises(expected_error):
                    accept_proposal(proposal, self.user)
            else:
                accept_proposal(proposal, self.user)

        assert _delta(before, _probe_outcomes()) == {expected_outcome: 1.0}

    def test_clickhouse_rejection_reports_the_real_error(self) -> None:
        proposal = self._propose()
        with patch.object(
            relationships,
            "execute_hogql_query",
            side_effect=ExposedCHQueryError("Illegal types of arguments", code=_ILLEGAL_TYPE_CODE),
        ):
            with self.assertRaises(ValidationError) as ctx:
                accept_proposal(proposal, self.user)

        assert "Illegal types of arguments" in str(cast(dict, ctx.exception.detail)["join"])

    def test_probe_tags_queries_with_the_data_catalog_product(self) -> None:
        # The probe attributed itself to the warehouse product, so its cost and failures landed under
        # another product in the generic posthog_query_execution_* series.
        proposal = self._propose()
        captured: dict[str, object] = {}

        def capture(*args: object, **kwargs: object) -> None:
            captured["product"] = get_query_tags().product

        with patch.object(relationships, "execute_hogql_query", side_effect=capture):
            accept_proposal(proposal, self.user)

        assert captured["product"] == Product.DATA_CATALOG
