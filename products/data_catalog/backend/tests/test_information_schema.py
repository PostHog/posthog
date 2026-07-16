import pytest
from posthog.test.base import APIBaseTest, ClickhouseTestMixin
from unittest.mock import patch

from django.db import connection
from django.test.utils import CaptureQueriesContext

from parameterized import parameterized

from posthog.hogql.context import HogQLContext
from posthog.hogql.database.database import Database
from posthog.hogql.errors import QueryError
from posthog.hogql.query import execute_hogql_query

from posthog.constants import AvailableFeature
from posthog.models.team import Team

from products.data_catalog.backend.logic import relationships
from products.data_catalog.backend.logic.certifications import certify, propose_certification
from products.data_catalog.backend.logic.metrics import upsert_metric
from products.data_catalog.backend.logic.relationships import accept_proposal, propose_relationship, reject_proposal
from products.data_catalog.backend.models import RelationshipProposal, TableCertification
from products.data_catalog.backend.models.metric import Metric
from products.data_modeling.backend.facade.models import DataWarehouseSavedQuery
from products.data_tools.backend.facade.models import DataWarehouseJoin
from products.product_analytics.backend.models.insight import Insight
from products.warehouse_sources.backend.facade.models import DataWarehouseTable, ExternalDataSource
from products.warehouse_sources.backend.facade.types import ExternalDataSourceType

from ee.models.rbac.access_control import AccessControl

_HOGQL = {"kind": "HogQLQuery", "query": "select count() from events"}
_COLUMNS = {"id": {"hogql": "StringDatabaseField", "clickhouse": "Nullable(String)", "schema_valid": True}}


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


class TestInformationSchemaCertificationsAndRelationships(ClickhouseTestMixin, APIBaseTest):
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

    def _enable_access_control(self) -> None:
        self.organization.available_product_features = [{"key": AvailableFeature.ACCESS_CONTROL, "name": "access"}]
        self.organization.save()

    def _create_warehouse_table(self, name: str) -> DataWarehouseTable:
        return DataWarehouseTable.objects.create(
            name=name,
            format="Parquet",
            team=self.team,
            url_pattern=f"s3://bucket/{name}",
            columns=_COLUMNS,
        )

    def _accept_relationship(self, proposal: RelationshipProposal) -> RelationshipProposal:
        with patch.object(relationships, "execute_hogql_query"):
            return accept_proposal(proposal, self.user)

    def test_certification_column_on_tables(self) -> None:
        table = self._create_warehouse_table("revenue")
        certify(propose_certification(team=self.team, user=self.user, table_id=str(table.id)), self.user)

        response = execute_hogql_query(
            "SELECT table_name, certification FROM system.information_schema.tables WHERE table_name = 'revenue'",
            team=self.team,
            context=self._context(),
        )
        assert {row[0]: row[1] for row in response.results}.get("revenue") == "certified"

    def test_proposed_certification_is_not_a_trust_mark(self) -> None:
        table = self._create_warehouse_table("revenue")
        propose_certification(team=self.team, user=self.user, table_id=str(table.id))

        response = execute_hogql_query(
            "SELECT certification FROM system.information_schema.tables WHERE table_name = 'revenue'",
            team=self.team,
            context=self._context(),
        )
        assert response.results == [(None,)]

    def test_deleted_source_certification_does_not_attach_to_same_name_table(self) -> None:
        source = ExternalDataSource.objects.create(team=self.team, source_type=ExternalDataSourceType.POSTGRES)
        deleted_table = DataWarehouseTable.objects.create(
            name="revenue",
            format="Parquet",
            team=self.team,
            external_data_source=source,
            url_pattern="s3://deleted-source/revenue",
            columns=_COLUMNS,
        )
        certify(propose_certification(team=self.team, user=self.user, table_id=str(deleted_table.id)), self.user)
        ExternalDataSource.objects.filter(pk=source.pk).update(deleted=True)
        self._create_warehouse_table("revenue")

        response = execute_hogql_query(
            "SELECT certification FROM system.information_schema.tables WHERE table_name = 'revenue'",
            team=self.team,
            context=self._context(),
        )
        assert response.results == [(None,)]

    def test_view_certification_does_not_bleed_onto_same_name_table(self) -> None:
        # A warehouse table and a view can share a name; each certification belongs to exactly one of
        # them. The warehouse table wins the catalog name collision, so its row must not inherit the
        # view's mark (would happen if certifications were keyed by name alone).
        self._create_warehouse_table("orders")
        view = DataWarehouseSavedQuery.objects.create(
            team=self.team, name="orders", query={"kind": "HogQLQuery", "query": "select 1"}, columns=_COLUMNS
        )
        certify(propose_certification(team=self.team, user=self.user, saved_query_id=str(view.id)), self.user)

        response = execute_hogql_query(
            "SELECT table_type, certification FROM system.information_schema.tables WHERE table_name = 'orders'",
            team=self.team,
            context=self._context(),
        )
        assert response.results == [("data_warehouse", None)]

    def test_columns_query_does_not_load_unrelated_catalog_models(self) -> None:
        with CaptureQueriesContext(connection) as queries:
            execute_hogql_query(
                "SELECT column_name FROM system.information_schema.columns WHERE table_name = 'events'",
                team=self.team,
                context=self._context(),
            )

        executed_sql = "\n".join(query["sql"] for query in queries.captured_queries)
        assert RelationshipProposal._meta.db_table not in executed_sql
        assert TableCertification._meta.db_table not in executed_sql

    @parameterized.expand([("proposed", False), ("rejected", True)])
    def test_unaccepted_relationship_is_not_query_discoverable(self, _name: str, rejected: bool) -> None:
        source = self._create_warehouse_table("catalog_orders")
        target = self._create_warehouse_table("catalog_customers")
        proposal = propose_relationship(
            team=self.team,
            user=self.user,
            source_table_name=source.name,
            source_table_key="id",
            joining_table_name=target.name,
            joining_table_key="id",
            field_name="customer",
            confidence=0.8,
            reasoning="Keys overlap",
        )
        if rejected:
            reject_proposal(proposal, self.user)

        response = execute_hogql_query(
            "SELECT source_column, target_table, target_column, relationship_kind, confidence, reasoning "
            "FROM system.information_schema.relationships "
            "WHERE source_table = 'catalog_orders' AND target_table = 'catalog_customers'",
            team=self.team,
            context=self._context(),
        )
        assert response.results == []

    def test_catalog_metadata_hidden_without_data_catalog_access(self) -> None:
        table = self._create_warehouse_table("revenue")
        certify(propose_certification(team=self.team, user=self.user, table_id=str(table.id)), self.user)
        source = self._create_warehouse_table("catalog_access_orders")
        target = self._create_warehouse_table("catalog_access_customers")
        proposal = propose_relationship(
            team=self.team,
            user=self.user,
            source_table_name=source.name,
            source_table_key="id",
            joining_table_name=target.name,
            joining_table_key="id",
            field_name="customer",
            confidence=0.9,
            reasoning="Sensitive review context",
        )
        self._accept_relationship(proposal)
        AccessControl.objects.create(team=self.team, resource="data_catalog", access_level="none")
        self._enable_access_control()

        context = self._context()
        certifications = execute_hogql_query(
            "SELECT certification FROM system.information_schema.tables WHERE table_name = 'revenue'",
            team=self.team,
            context=context,
        )
        relationship_context = execute_hogql_query(
            "SELECT confidence, reasoning FROM system.information_schema.relationships "
            "WHERE source_table = 'catalog_access_orders' AND target_table = 'catalog_access_customers'",
            team=self.team,
            context=context,
        )
        assert certifications.results == [(None,)]
        assert relationship_context.results == [(None, None)]

    @parameterized.expand([("source", "orders"), ("target", "customers")])
    def test_accepted_context_hidden_when_endpoint_table_is_denied(self, _name: str, denied_table_name: str) -> None:
        source = self._create_warehouse_table("orders")
        target = self._create_warehouse_table("customers")
        proposal = propose_relationship(
            team=self.team,
            user=self.user,
            source_table_name=source.name,
            source_table_key="id",
            joining_table_name=target.name,
            joining_table_key="id",
            field_name="customer",
            confidence=0.7,
            reasoning="Must not leak",
        )
        self._accept_relationship(proposal)
        response = execute_hogql_query(
            "SELECT reasoning FROM system.information_schema.relationships "
            "WHERE source_table = 'orders' AND target_table = 'customers' AND reasoning IS NOT NULL",
            team=self.team,
            context=self._context(denied_tables={denied_table_name}),
        )
        assert response.results == []

    def test_accepted_join_is_enriched_with_reviewed_provenance(self) -> None:
        proposal = propose_relationship(
            team=self.team,
            user=self.user,
            source_table_name="events",
            source_table_key="distinct_id",
            joining_table_name="persons",
            joining_table_key="id",
            field_name="reviewed_person",
            confidence=0.9,
            reasoning="97% key match",
        )
        self._accept_relationship(proposal)

        response = execute_hogql_query(
            "SELECT confidence, reasoning FROM system.information_schema.relationships "
            "WHERE source_table = 'events' AND relationship_kind = 'lazy_join' AND reasoning IS NOT NULL",
            team=self.team,
            context=self._context(),
        )
        assert [row[1] for row in response.results] == ["97% key match"]
        assert response.results[0][0] == 0.9

    def test_replacement_join_does_not_inherit_deleted_join_provenance(self) -> None:
        proposal = propose_relationship(
            team=self.team,
            user=self.user,
            source_table_name="events",
            source_table_key="distinct_id",
            joining_table_name="persons",
            joining_table_key="id",
            field_name="reviewed_person",
            confidence=0.9,
            reasoning="Original review",
        )
        accepted = self._accept_relationship(proposal)

        assert accepted.created_join_id is not None
        DataWarehouseJoin.objects.get(pk=accepted.created_join_id).soft_delete()
        DataWarehouseJoin.objects.create(
            team=self.team,
            source_table_name="events",
            source_table_key="distinct_id",
            joining_table_name="persons",
            joining_table_key="id",
            field_name="reviewed_person",
        )

        response = execute_hogql_query(
            "SELECT confidence, reasoning FROM system.information_schema.relationships "
            "WHERE source_table = 'events' AND source_column = 'distinct_id' AND target_table = 'persons' "
            "AND relationship_kind = 'lazy_join' AND reasoning IS NOT NULL",
            team=self.team,
            context=self._context(),
        )
        assert response.results == []
