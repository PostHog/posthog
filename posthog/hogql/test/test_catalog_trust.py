from posthog.test.base import BaseTest
from unittest.mock import patch

from django.contrib.auth.models import AnonymousUser

from parameterized import parameterized

from posthog.hogql.catalog_trust import build_data_catalog_trust_warning
from posthog.hogql.context import HogQLContext
from posthog.hogql.database.database import Database
from posthog.hogql.parser import parse_select
from posthog.hogql.resolver import resolve_types
from posthog.hogql.visitor import clone_expr

from products.data_catalog.backend.facade.api import (
    approve_metric,
    certify,
    deprecate,
    propose_certification,
    upsert_metric,
)
from products.warehouse_sources.backend.facade.models import DataWarehouseCredential, DataWarehouseTable

_FLAG_TARGET = "products.data_catalog.backend.facade.flags.is_data_catalog_enabled"


class TestCatalogTrustWarning(BaseTest):
    def _create_table(self, name: str) -> DataWarehouseTable:
        credentials = DataWarehouseCredential.objects.create(access_key="key", access_secret="secret", team=self.team)
        return DataWarehouseTable.objects.create(
            name=name,
            format="Parquet",
            team=self.team,
            credential=credentials,
            url_pattern="https://bucket.s3/data/*",
            columns={"id": {"hogql": "StringDatabaseField", "clickhouse": "Nullable(String)", "schema_valid": True}},
        )

    def _create_approved_metric(self, name: str = "monthly_recurring_revenue") -> None:
        metric = upsert_metric(
            team=self.team,
            user=self.user,
            name=name,
            description="Canonical MRR",
            definition={"kind": "HogQLQuery", "query": "SELECT count() FROM events"},
        )
        approve_metric(metric, self.user)

    _CURRENT_USER = object()

    def _warning_for(self, query: str, *, user=_CURRENT_USER, flag: bool = True):
        database = Database.create_for(team=self.team)
        context = HogQLContext(team_id=self.team.pk, team=self.team, database=database, enable_select_queries=True)
        resolved = resolve_types(clone_expr(parse_select(query), True), context, dialect="hogql")
        resolved_user = self.user if user is self._CURRENT_USER else user
        with patch(_FLAG_TARGET, return_value=flag):
            return build_data_catalog_trust_warning(self.team, resolved_user, lambda: resolved.type)

    def test_uncertified_table_with_approved_metric_fires_advisory(self):
        self._create_table("customer_rollup")
        self._create_approved_metric()

        warning = self._warning_for("SELECT id FROM customer_rollup")

        assert warning is not None
        assert warning.uncertified_tables == ["customer_rollup"]
        assert warning.approved_metrics == ["monthly_recurring_revenue"]
        assert "system.information_schema.metrics" in warning.message
        assert "customer_rollup" in warning.message

    def test_certified_table_is_silent(self):
        table = self._create_table("customer_rollup")
        self._create_approved_metric()
        certify(propose_certification(team=self.team, user=self.user, table_id=str(table.id)), self.user)

        assert self._warning_for("SELECT id FROM customer_rollup") is None

    def test_deprecated_certification_still_fires(self):
        table = self._create_table("customer_rollup")
        self._create_approved_metric()
        deprecate(propose_certification(team=self.team, user=self.user, table_id=str(table.id)), self.user)

        warning = self._warning_for("SELECT id FROM customer_rollup")

        assert warning is not None
        assert warning.uncertified_tables == ["customer_rollup"]

    def test_silent_without_approved_metrics(self):
        self._create_table("customer_rollup")
        upsert_metric(
            team=self.team,
            user=self.user,
            name="activation_rate",
            description="Proposed only",
            definition={"kind": "HogQLQuery", "query": "SELECT count() FROM events"},
        )

        assert self._warning_for("SELECT id FROM customer_rollup") is None

    def test_silent_when_flag_off(self):
        self._create_table("customer_rollup")
        self._create_approved_metric()

        assert self._warning_for("SELECT id FROM customer_rollup", flag=False) is None

    def test_silent_for_events_only_query(self):
        self._create_table("customer_rollup")
        self._create_approved_metric()

        assert self._warning_for("SELECT event FROM events") is None

    @parameterized.expand(
        [
            ("anonymous_viewer", AnonymousUser()),
            ("no_user", None),
        ]
    )
    def test_withheld_from_unauthenticated_principals(self, _name, user):
        # The advisory names catalog metadata (metric names) — same posture as
        # warehouse source attribution: never shown to shared-link viewers.
        self._create_table("customer_rollup")
        self._create_approved_metric()

        assert self._warning_for("SELECT id FROM customer_rollup", user=user) is None

    def test_executor_attaches_warning_to_query_response(self):
        # End-to-end through HogQLQueryExecutor.execute(): the advisory must ride the
        # response `warnings` list, where the agent-facing formatter picks it up.
        from posthog.hogql.query import execute_hogql_query

        self._create_table("customer_rollup")
        self._create_approved_metric()

        with (
            patch(_FLAG_TARGET, return_value=True),
            patch("posthog.hogql.query.sync_execute", return_value=([], [])),
        ):
            response = execute_hogql_query(query="SELECT id FROM customer_rollup", team=self.team, user=self.user)

        assert response.warnings is not None
        trust = [w for w in response.warnings if getattr(w, "type", None) == "data_catalog_trust"]
        assert len(trust) == 1
        assert trust[0].uncertified_tables == ["customer_rollup"]

    def test_lookup_failure_never_breaks_the_query(self):
        self._create_table("customer_rollup")
        self._create_approved_metric()

        with patch(
            "products.data_catalog.backend.facade.api.certifications_for_team",
            side_effect=RuntimeError("catalog down"),
        ):
            assert self._warning_for("SELECT id FROM customer_rollup") is None
