from posthog.test.base import BaseTest
from unittest.mock import MagicMock, patch

from django.db import IntegrityError

from parameterized import parameterized
from rest_framework.exceptions import ValidationError

from products.data_catalog.backend.facade.enums import CreatedSource, MetricStatus
from products.data_catalog.backend.logic import metrics
from products.data_catalog.backend.logic.metrics import soft_delete_metric, update_metric, upsert_metric
from products.data_catalog.backend.logic.validation import validate_metric_definition
from products.data_catalog.backend.models import Metric


class TestMetricUpsert(BaseTest):
    def _upsert(self, name: str, description: str = "desc", **kwargs) -> Metric:
        return upsert_metric(team=self.team, user=self.user, name=name, description=description, **kwargs)

    def test_creates_proposed_metric(self) -> None:
        metric = self._upsert("mrr", created_source=CreatedSource.AI_GENERATED)
        assert metric.status == MetricStatus.PROPOSED
        assert metric.created_source == CreatedSource.AI_GENERATED
        assert metric.owner_id == self.user.id

    def test_same_name_refines_not_duplicates(self) -> None:
        first = self._upsert("mrr", description="v1")
        second = self._upsert("mrr", description="v2")
        assert first.id == second.id
        assert Metric.objects.for_team(self.team.id).count() == 1
        assert Metric.objects.for_team(self.team.id).get().description == "v2"

    def test_refine_leaves_unspecified_fields_untouched(self) -> None:
        self._upsert(
            "mrr",
            created_source=CreatedSource.AI_GENERATED,
            ai_model="claude",
            definition={"kind": "HogQLQuery", "query": "select count() from events"},
        )
        refined = self._upsert("mrr", description="v2")
        assert refined.description == "v2"
        assert refined.definition is not None
        assert refined.definition["kind"] == "HogQLQuery"
        assert refined.referenced_table_names == ["events"]
        assert refined.created_source == CreatedSource.AI_GENERATED
        assert refined.ai_model == "claude"

    def test_upsert_resurrects_soft_deleted_as_proposed(self) -> None:
        metric = self._upsert("mrr")
        Metric.objects.for_team(self.team.id).filter(pk=metric.pk).update(status=MetricStatus.APPROVED)
        metric.refresh_from_db()
        soft_delete_metric(metric)

        resurrected = self._upsert("mrr", description="back")
        assert resurrected.id == metric.id
        assert resurrected.deleted is False
        assert resurrected.status == MetricStatus.PROPOSED
        assert resurrected.description == "back"

    @parameterized.expand([("bad name",), ("1leading_digit",), ("has-dash",), ("",)])
    def test_rejects_invalid_names(self, name: str) -> None:
        with self.assertRaises(ValidationError):
            self._upsert(name)

    def test_concurrent_create_retries_to_single_row(self) -> None:
        # Simulate the race: the pre-check misses, create hits the unique constraint (IntegrityError),
        # and the retry finds and refines the row the other writer created. Guards the except branch.
        winner = self._upsert("mrr", description="winner")

        mock_qs = MagicMock()
        mock_qs.filter.return_value.select_for_update.return_value.first.side_effect = [None, winner]
        mock_qs.create.side_effect = IntegrityError("duplicate key")

        with patch.object(metrics.Metric.objects, "for_team", return_value=mock_qs):
            result = self._upsert("mrr", description="racer")

        assert result.id == winner.id
        assert Metric.objects.for_team(self.team.id).count() == 1


class TestMetricUpdate(BaseTest):
    def test_update_changes_fields(self) -> None:
        metric = upsert_metric(team=self.team, user=self.user, name="mrr", description="v1")
        updated = update_metric(metric, team=self.team, user=self.user, description="v2", unit="usd")
        assert updated.description == "v2"
        assert updated.unit == "usd"

    def test_update_rejects_name_change(self) -> None:
        metric = upsert_metric(team=self.team, user=self.user, name="mrr", description="v1")
        with self.assertRaises(ValidationError):
            update_metric(metric, team=self.team, user=self.user, name="arr")

    def test_update_definition_reextracts_tables(self) -> None:
        metric = upsert_metric(team=self.team, user=self.user, name="mrr", description="v1")
        updated = update_metric(
            metric,
            team=self.team,
            user=self.user,
            definition={"kind": "HogQLQuery", "query": "select count() from events"},
        )
        assert updated.referenced_table_names == ["events"]


class TestValidateMetricDefinition(BaseTest):
    def test_valid_hogql_extracts_referenced_tables(self) -> None:
        _, tables = validate_metric_definition(
            {"kind": "HogQLQuery", "query": "select count() from events"}, self.team, self.user
        )
        assert tables == ["events"]

    def test_insight_viz_node_is_unwrapped(self) -> None:
        canonical, _ = validate_metric_definition(
            {"kind": "InsightVizNode", "source": {"kind": "HogQLQuery", "query": "select 1"}},
            self.team,
            self.user,
        )
        assert canonical["kind"] == "HogQLQuery"

    def test_markdown_definition_accepted(self) -> None:
        canonical, tables = validate_metric_definition(
            {"kind": "MarkdownDefinition", "markdown": "1. Sum the paid subscriptions over the month."},
            self.team,
            self.user,
        )
        assert canonical["kind"] == "MarkdownDefinition"
        assert tables == []

    @parameterized.expand(
        [
            ("unsupported_kind", {"kind": "RetentionQuery"}),
            ("raw_connection", {"kind": "HogQLQuery", "query": "select 1", "connectionId": "abc"}),
            ("raw_query", {"kind": "HogQLQuery", "query": "select 1", "sendRawQuery": True}),
            ("bad_sql", {"kind": "HogQLQuery", "query": "not valid sql !!!"}),
            ("no_kind", {"query": "select 1"}),
            ("markdown_empty", {"kind": "MarkdownDefinition", "markdown": "   "}),
            ("markdown_smuggled_query", {"kind": "MarkdownDefinition", "markdown": "x", "query": "select 1"}),
        ]
    )
    def test_rejects_invalid_definitions(self, _name: str, definition: dict) -> None:
        with self.assertRaises(ValidationError):
            validate_metric_definition(definition, self.team, self.user)
