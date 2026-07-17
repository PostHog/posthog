import pytest
from posthog.test.base import APIBaseTest, ClickhouseTestMixin
from unittest.mock import patch

from parameterized import parameterized

from posthog.hogql.context import HogQLContext
from posthog.hogql.database.database import Database
from posthog.hogql.errors import QueryError
from posthog.hogql.query import execute_hogql_query

from posthog.constants import AvailableFeature
from posthog.models.team import Team

from products.data_catalog.backend.logic.metrics import upsert_metric
from products.data_catalog.backend.models.metric import Metric
from products.product_analytics.backend.models.insight import Insight

from ee.models.rbac.access_control import AccessControl

_HOGQL = {"kind": "HogQLQuery", "query": "select count() from events"}


class TestInformationSchemaMetrics(ClickhouseTestMixin, APIBaseTest):
    def setUp(self) -> None:
        super().setUp()
        flag_patch = patch("products.data_catalog.backend.facade.flags.is_data_catalog_enabled", return_value=True)
        flag_patch.start()
        self.addCleanup(flag_patch.stop)

    def _context(self, denied_tables: set[str] | None = None) -> HogQLContext:
        database = Database.create_for(team=self.team, user=self.user)
        if denied_tables:
            database._denied_tables |= denied_tables
        return HogQLContext(team=self.team, team_id=self.team.pk, database=database)

    def _rows(self, where: str = "", context: HogQLContext | None = None) -> dict:
        response = execute_hogql_query(
            f"SELECT name, description, status, is_drifted, definition_kind FROM system.information_schema.metrics {where}",
            team=self.team,
            context=context or self._context(),
        )
        return {row[0]: row for row in response.results}

    def test_metric_is_discoverable_via_ilike(self) -> None:
        upsert_metric(
            team=self.team, user=self.user, name="mrr", description="Monthly recurring revenue", definition=_HOGQL
        )
        rows = self._rows("WHERE name ILIKE '%mrr%'")
        assert "mrr" in rows
        assert rows["mrr"][1] == "Monthly recurring revenue"
        assert rows["mrr"][2] == "proposed"
        assert rows["mrr"][4] == "HogQLQuery"

        listing = execute_hogql_query(
            "SELECT table_name FROM system.information_schema.tables WHERE table_name = 'system.information_schema.metrics'",
            team=self.team,
            context=self._context(),
        )
        assert listing.results == [("system.information_schema.metrics",)]

    def test_metrics_table_absent_when_flag_off(self) -> None:
        upsert_metric(team=self.team, user=self.user, name="mrr", description="d", definition=_HOGQL)
        with patch("products.data_catalog.backend.facade.flags.is_data_catalog_enabled", return_value=False):
            listing = execute_hogql_query(
                "SELECT table_name FROM system.information_schema.tables WHERE table_name = 'system.information_schema.metrics'",
                team=self.team,
                context=self._context(),
            )
            assert listing.results == []

            with pytest.raises(QueryError, match="Unknown table"):
                execute_hogql_query(
                    "SELECT name FROM system.information_schema.metrics", team=self.team, context=self._context()
                )

    def test_is_drifted_reflects_source_insight(self) -> None:
        insight = Insight.objects.create(team=self.team, created_by=self.user, query=_HOGQL)
        upsert_metric(
            team=self.team, user=self.user, name="active", description="d", source_insight_short_id=insight.short_id
        )
        assert self._rows("WHERE name = 'active'")["active"][3] in (False, 0)

        Insight.objects.filter(pk=insight.pk).update(
            query={"kind": "HogQLQuery", "query": "select count() from persons"}
        )
        assert self._rows("WHERE name = 'active'")["active"][3] in (True, 1)

    def test_team_isolation(self) -> None:
        other = Team.objects.create_with_data(organization=self.organization, initiating_user=self.user, name="Other")
        upsert_metric(team=other, user=self.user, name="theirs", description="d", definition=_HOGQL)
        assert "theirs" not in self._rows()

    @parameterized.expand(
        [
            ("exact_bare", ["denied_source"], {"denied_source"}),
            ("qualified_reference_bare_denied", ["schema.denied_source"], {"denied_source"}),
            ("bare_reference_qualified_denied", ["charges"], {"stripe.charges"}),
            ("case_insensitive", ["Schema.Denied_Source"], {"denied_source"}),
        ]
    )
    def test_metric_hidden_when_referenced_table_denied(
        self, _name: str, referenced: list[str], denied: set[str]
    ) -> None:
        allowed = upsert_metric(
            team=self.team, user=self.user, name="allowed_metric", description="d", definition=_HOGQL
        )
        hidden = upsert_metric(team=self.team, user=self.user, name="hidden_metric", description="d", definition=_HOGQL)
        Metric.objects.for_team(self.team.pk).filter(pk=allowed.pk).update(referenced_table_names=["safe_source"])
        Metric.objects.for_team(self.team.pk).filter(pk=hidden.pk).update(referenced_table_names=referenced)

        names = set(self._rows(context=self._context(denied_tables=denied)))
        assert "allowed_metric" in names
        assert "hidden_metric" not in names

    def test_metrics_hidden_without_data_catalog_access(self) -> None:
        upsert_metric(team=self.team, user=self.user, name="mrr", description="d", definition=_HOGQL)
        AccessControl.objects.create(team=self.team, resource="data_catalog", access_level="none")
        self.organization.available_product_features = [{"key": AvailableFeature.ACCESS_CONTROL, "name": "access"}]
        self.organization.save()

        assert self._rows() == {}

    def test_metrics_hidden_without_access_control_context(self) -> None:
        upsert_metric(team=self.team, user=self.user, name="mrr", description="d", definition=_HOGQL)
        # No user / access-control context (service token, shared link) must fail closed.
        response = execute_hogql_query("SELECT name FROM system.information_schema.metrics", team=self.team)
        assert response.results == []
