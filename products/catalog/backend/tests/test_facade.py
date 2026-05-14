from uuid import uuid4

import pytest
from posthog.test.base import BaseTest

from products.catalog.backend.facade.api import CatalogAPI
from products.catalog.backend.facade.contracts import (
    AppendColumnNoteParams,
    AppendNodeNoteParams,
    CatalogGraphDTO,
    CatalogMetricDTO,
    CatalogNodeDTO,
    ProposeRelationshipParams,
    RecordJoinParams,
    UpdateColumnParams,
    UpdateMetricParams,
    UpdateNodeParams,
    UpdateRelationshipParams,
    UpsertColumnParams,
    UpsertMetricParams,
    UpsertNodeParams,
)
from products.catalog.backend.logic import UnknownTableError, _resolve_node_kind_and_name
from products.catalog.backend.models import CatalogColumn, CatalogNode, CatalogRelationship


class TestCatalogAPIUpsert(BaseTest):
    def test_upsert_node_creates_new(self) -> None:
        dto = CatalogAPI.upsert_node(
            UpsertNodeParams(
                team_id=self.team.pk,
                kind="posthog_table",
                name="events",
                synthetic_description="Raw event stream",
            )
        )
        assert isinstance(dto, CatalogNodeDTO)
        assert dto.name == "events"
        assert dto.description == "Raw event stream"
        assert dto.last_traversed_at is not None

    def test_upsert_node_is_idempotent(self) -> None:
        first = CatalogAPI.upsert_node(UpsertNodeParams(team_id=self.team.pk, kind="posthog_table", name="events"))
        second = CatalogAPI.upsert_node(
            UpsertNodeParams(
                team_id=self.team.pk,
                kind="posthog_table",
                name="events",
                synthetic_description="Raw event stream",
            )
        )
        assert first.id == second.id
        assert second.description == "Raw event stream"

    def test_upsert_column_is_idempotent(self) -> None:
        node = CatalogAPI.upsert_node(UpsertNodeParams(team_id=self.team.pk, kind="posthog_table", name="events"))
        first = CatalogAPI.upsert_column(
            UpsertColumnParams(node_id=node.id, name="distinct_id", clickhouse_type="String")
        )
        second = CatalogAPI.upsert_column(
            UpsertColumnParams(
                node_id=node.id,
                name="distinct_id",
                clickhouse_type="String",
                synthetic_description="Identifier for the user that emitted this event",
                semantic_type="entity_id",
            )
        )
        assert first.id == second.id
        assert second.description is not None and second.description.startswith("Identifier")
        assert second.semantic_type == "entity_id"

    def test_propose_relationship_is_idempotent_on_edge_tuple(self) -> None:
        source = CatalogAPI.upsert_node(UpsertNodeParams(team_id=self.team.pk, kind="warehouse_table", name="orders"))
        target = CatalogAPI.upsert_node(
            UpsertNodeParams(team_id=self.team.pk, kind="warehouse_table", name="customers")
        )
        first = CatalogAPI.propose_relationship(
            ProposeRelationshipParams(
                team_id=self.team.pk,
                source_node_id=source.id,
                target_node_id=target.id,
                kind="foreign_key",
                confidence=0.7,
                reasoning="First pass",
            )
        )
        second = CatalogAPI.propose_relationship(
            ProposeRelationshipParams(
                team_id=self.team.pk,
                source_node_id=source.id,
                target_node_id=target.id,
                kind="foreign_key",
                confidence=0.9,
                reasoning="Second pass — stronger evidence",
            )
        )
        assert first.id == second.id
        assert second.confidence == 0.9
        assert second.reasoning.startswith("Second pass")


class TestCatalogAPIGetGraph(BaseTest):
    def test_get_graph_returns_nodes_columns_and_relationships(self) -> None:
        events = CatalogAPI.upsert_node(UpsertNodeParams(team_id=self.team.pk, kind="posthog_table", name="events"))
        persons = CatalogAPI.upsert_node(UpsertNodeParams(team_id=self.team.pk, kind="posthog_table", name="persons"))
        CatalogAPI.upsert_column(
            UpsertColumnParams(
                node_id=events.id, name="distinct_id", clickhouse_type="String", semantic_type="entity_id"
            )
        )
        CatalogAPI.upsert_column(
            UpsertColumnParams(node_id=persons.id, name="id", clickhouse_type="UUID", semantic_type="entity_id")
        )
        CatalogAPI.propose_relationship(
            ProposeRelationshipParams(
                team_id=self.team.pk,
                source_node_id=events.id,
                target_node_id=persons.id,
                kind="foreign_key",
                confidence=0.8,
                reasoning="events.distinct_id resolves to a person",
            )
        )

        graph = CatalogAPI.get_graph(self.team.pk)
        assert isinstance(graph, CatalogGraphDTO)
        assert len(graph.nodes) == 2
        assert {n.name for n in graph.nodes} == {"events", "persons"}
        assert len(graph.relationships) == 1
        assert graph.relationships[0].confidence == 0.8

    def test_list_nodes_returns_team_nodes_ordered(self) -> None:
        CatalogAPI.upsert_node(
            UpsertNodeParams(team_id=self.team.pk, kind="warehouse_table", name="orders", business_domain="billing")
        )
        CatalogAPI.upsert_node(
            UpsertNodeParams(team_id=self.team.pk, kind="posthog_table", name="events", business_domain="product_usage")
        )
        CatalogAPI.upsert_node(
            UpsertNodeParams(team_id=self.team.pk, kind="warehouse_table", name="invoices", business_domain="billing")
        )

        nodes = CatalogAPI.list_nodes(self.team.pk)

        names = [n.name for n in nodes]
        assert names == ["invoices", "orders", "events"]

    def test_get_graph_does_not_leak_across_teams(self) -> None:
        CatalogAPI.upsert_node(UpsertNodeParams(team_id=self.team.pk, kind="posthog_table", name="events"))

        from posthog.models import Organization, Team
        from posthog.models.project import Project

        other_org = Organization.objects.create(name="other_org")
        other_project = Project.objects.create(id=Team.objects.increment_id_sequence(), organization=other_org)
        other_team = Team.objects.create(id=other_project.id, project=other_project, organization=other_org)

        graph = CatalogAPI.get_graph(other_team.pk)
        assert graph.nodes == ()
        assert graph.relationships == ()


class TestCatalogAPIUpdate(BaseTest):
    def test_update_node_writes_only_supplied_fields(self) -> None:
        node = CatalogAPI.upsert_node(
            UpsertNodeParams(
                team_id=self.team.pk,
                kind="warehouse_table",
                name="stripe_charges",
                synthetic_description="initial",
                semantic_role="fact",
                business_domain="billing",
                tags=("stripe",),
            )
        )

        updated = CatalogAPI.update_node(
            UpdateNodeParams(
                team_id=self.team.pk,
                node_id=node.id,
                synthetic_description="refined description",
            )
        )

        assert updated is not None
        assert updated.description == "refined description"
        assert updated.semantic_role == "fact"
        assert updated.business_domain == "billing"
        assert updated.tags == ("stripe",)

    def test_update_node_status_records_review(self) -> None:
        node = CatalogAPI.upsert_node(
            UpsertNodeParams(team_id=self.team.pk, kind="warehouse_table", name="stripe_charges")
        )
        assert node.status == "proposed"
        assert node.reviewed_at is None

        approved = CatalogAPI.update_node(
            UpdateNodeParams(
                team_id=self.team.pk,
                node_id=node.id,
                status="approved",
                reviewed_by_id=self.user.pk,
            )
        )

        assert approved is not None
        assert approved.status == "approved"
        assert approved.reviewed_at is not None

    def test_update_node_returns_none_for_missing(self) -> None:
        import uuid

        result = CatalogAPI.update_node(
            UpdateNodeParams(team_id=self.team.pk, node_id=uuid.uuid4(), synthetic_description="x")
        )
        assert result is None

    def test_update_node_does_not_leak_across_teams(self) -> None:
        node = CatalogAPI.upsert_node(
            UpsertNodeParams(team_id=self.team.pk, kind="warehouse_table", name="stripe_charges")
        )
        result = CatalogAPI.update_node(
            UpdateNodeParams(team_id=self.team.pk + 9999, node_id=node.id, synthetic_description="hijack")
        )
        assert result is None

    def test_update_column_writes_only_supplied_fields(self) -> None:
        node = CatalogAPI.upsert_node(
            UpsertNodeParams(team_id=self.team.pk, kind="warehouse_table", name="stripe_charges")
        )
        column = CatalogAPI.upsert_column(
            UpsertColumnParams(
                node_id=node.id,
                name="amount_usd_cents",
                clickhouse_type="UInt64",
                semantic_type="measure",
                pii_class="public",
            )
        )

        updated = CatalogAPI.update_column(
            UpdateColumnParams(
                team_id=self.team.pk,
                column_id=column.id,
                synthetic_description="Charge amount in USD cents",
                semantic_type="monetary",
            )
        )

        assert updated is not None
        assert updated.description == "Charge amount in USD cents"
        assert updated.semantic_type == "monetary"
        assert updated.pii_class == "public"

    def test_update_relationship_accept_records_review(self) -> None:
        source = CatalogAPI.upsert_node(UpsertNodeParams(team_id=self.team.pk, kind="warehouse_table", name="orders"))
        target = CatalogAPI.upsert_node(
            UpsertNodeParams(team_id=self.team.pk, kind="warehouse_table", name="customers")
        )
        rel = CatalogAPI.propose_relationship(
            ProposeRelationshipParams(
                team_id=self.team.pk,
                source_node_id=source.id,
                target_node_id=target.id,
                kind="foreign_key",
                confidence=0.6,
            )
        )
        assert rel.status == "proposed"

        accepted = CatalogAPI.update_relationship(
            UpdateRelationshipParams(
                team_id=self.team.pk,
                relationship_id=rel.id,
                status="accepted",
                reviewed_by_id=self.user.pk,
            )
        )

        assert accepted is not None
        assert accepted.status == "accepted"


class TestCatalogAPIMetrics(BaseTest):
    def _upsert(self, name: str = "monthly_recurring_revenue", **overrides) -> CatalogMetricDTO:
        return CatalogAPI.upsert_metric(
            UpsertMetricParams(
                team_id=self.team.pk,
                name=name,
                description=overrides.get("description", "MRR across active subscriptions"),
                definition=overrides.get(
                    "definition",
                    {"kind": "EventsNode", "event": "subscription_started", "math": "dau"},
                ),
                confidence=overrides.get("confidence", 0.9),
            )
        )

    def test_upsert_bundles_node_metadata_into_metric_dto(self) -> None:
        dto = self._upsert()
        assert dto.name == "monthly_recurring_revenue"
        assert dto.definition["kind"] == "EventsNode"
        assert dto.node.kind == "metric"
        assert dto.node.status == "proposed"
        assert dto.node.confidence == 0.9

    def test_list_metrics_returns_team_metrics_only(self) -> None:
        self._upsert(name="mrr")
        self._upsert(name="arr")
        other_team = self.organization.teams.create(name="other")
        CatalogAPI.upsert_metric(
            UpsertMetricParams(
                team_id=other_team.pk,
                name="leaky",
                definition={"kind": "EventsNode", "event": "signup", "math": "dau"},
            )
        )
        metrics = CatalogAPI.list_metrics(self.team.pk)
        assert sorted(m.name for m in metrics) == ["arr", "mrr"]

    def test_get_metric_returns_none_for_missing(self) -> None:
        assert CatalogAPI.get_metric(self.team.pk, uuid4()) is None

    def test_update_metric_writes_only_supplied_fields(self) -> None:
        original = self._upsert()
        updated = CatalogAPI.update_metric(
            UpdateMetricParams(
                team_id=self.team.pk,
                metric_id=original.id,
                description="Refined MRR description",
            )
        )
        assert updated is not None
        assert updated.description == "Refined MRR description"
        # Definition untouched
        assert updated.definition == original.definition

    def test_update_metric_returns_none_for_missing(self) -> None:
        assert (
            CatalogAPI.update_metric(UpdateMetricParams(team_id=self.team.pk, metric_id=uuid4(), description="x"))
            is None
        )


class TestResolveNodeKindAndName(BaseTest):
    """HogQL-driven kind resolution used by the conversation append + read-context helpers."""

    def test_resolves_posthog_table(self) -> None:
        kind, name = _resolve_node_kind_and_name(self.team, "events")
        assert kind == CatalogNode.Kind.POSTHOG_TABLE
        assert name == "events"

    def test_resolves_system_table_qualified(self) -> None:
        kind, name = _resolve_node_kind_and_name(self.team, "system.dashboards")
        assert kind == CatalogNode.Kind.SYSTEM_TABLE
        # Storage name is the leaf, matching how sync_system_tables_for_team would seed it.
        assert name == "dashboards"

    def test_raises_for_unknown_table(self) -> None:
        with pytest.raises(UnknownTableError):
            _resolve_node_kind_and_name(self.team, "definitely_not_a_real_table_zzz")


class TestCatalogAPIAppendNoteAndJoin(BaseTest):
    """End-to-end behavior of the conversation-driven append facade methods."""

    def test_append_node_note_creates_node_on_miss(self) -> None:
        dto = CatalogAPI.append_node_note(
            self.team,
            AppendNodeNoteParams(
                team_id=self.team.pk,
                table_name="events",
                note="excludes test traffic",
                attribution="[@alice 2026-05-14]",
            ),
        )
        assert dto.description == "[@alice 2026-05-14] excludes test traffic"
        # Node was created on the fly with the kind HogQL resolved.
        node = CatalogNode.objects.get(team=self.team, kind=CatalogNode.Kind.POSTHOG_TABLE, name="events")
        assert node.synthetic_description == "[@alice 2026-05-14] excludes test traffic"

    def test_append_node_note_appends_on_repeat(self) -> None:
        params1 = AppendNodeNoteParams(
            team_id=self.team.pk,
            table_name="events",
            note="excludes test traffic",
            attribution="[@alice 2026-05-14]",
        )
        params2 = AppendNodeNoteParams(
            team_id=self.team.pk,
            table_name="events",
            note="$pageview is the most common event",
            attribution="[@bob 2026-05-20]",
        )
        CatalogAPI.append_node_note(self.team, params1)
        result = CatalogAPI.append_node_note(self.team, params2)
        assert result.description == (
            "[@alice 2026-05-14] excludes test traffic\n[@bob 2026-05-20] $pageview is the most common event"
        )

    def test_append_node_note_preserves_existing_description(self) -> None:
        CatalogAPI.upsert_node(
            UpsertNodeParams(
                team_id=self.team.pk,
                kind=CatalogNode.Kind.POSTHOG_TABLE,
                name="events",
                synthetic_description="Raw event stream from SDKs.",
            )
        )
        result = CatalogAPI.append_node_note(
            self.team,
            AppendNodeNoteParams(
                team_id=self.team.pk,
                table_name="events",
                note="excludes staging traffic",
                attribution="[@carol 2026-05-21]",
            ),
        )
        assert result.description == ("Raw event stream from SDKs.\n[@carol 2026-05-21] excludes staging traffic")

    def test_append_node_note_raises_for_unknown_table(self) -> None:
        with pytest.raises(UnknownTableError):
            CatalogAPI.append_node_note(
                self.team,
                AppendNodeNoteParams(
                    team_id=self.team.pk,
                    table_name="definitely_not_a_real_table_zzz",
                    note="anything",
                    attribution="[@alice 2026-05-14]",
                ),
            )

    def test_append_column_note_creates_column_on_miss(self) -> None:
        result = CatalogAPI.append_column_note(
            self.team,
            AppendColumnNoteParams(
                team_id=self.team.pk,
                table_name="events",
                column_name="timestamp",
                note="UTC, not user local time",
                attribution="[@alice 2026-05-14]",
            ),
        )
        assert result.description == "[@alice 2026-05-14] UTC, not user local time"
        column = CatalogColumn.objects.get(team=self.team, node__name="events", name="timestamp")
        assert column.synthetic_description == "[@alice 2026-05-14] UTC, not user local time"

    def test_append_column_note_appends_on_repeat(self) -> None:
        params1 = AppendColumnNoteParams(
            team_id=self.team.pk,
            table_name="events",
            column_name="timestamp",
            note="UTC",
            attribution="[@alice 2026-05-14]",
        )
        params2 = AppendColumnNoteParams(
            team_id=self.team.pk,
            table_name="events",
            column_name="timestamp",
            note="ingestion time, not the user's wall-clock",
            attribution="[@bob 2026-05-15]",
        )
        CatalogAPI.append_column_note(self.team, params1)
        result = CatalogAPI.append_column_note(self.team, params2)
        assert result.description == (
            "[@alice 2026-05-14] UTC\n[@bob 2026-05-15] ingestion time, not the user's wall-clock"
        )

    def test_record_join_creates_accepted_edge(self) -> None:
        result = CatalogAPI.record_join(
            self.team,
            RecordJoinParams(
                team_id=self.team.pk,
                source_table="events",
                target_table="persons",
                source_column="distinct_id",
                target_column=None,
                note="events.distinct_id maps to a person",
                attribution="[@alice 2026-05-14]",
            ),
        )
        assert result.kind == CatalogRelationship.Kind.DECLARED_JOIN
        assert result.status == CatalogRelationship.Status.ACCEPTED
        assert result.confidence == 1.0
        assert result.reasoning == "[@alice 2026-05-14] events.distinct_id maps to a person"
        assert result.source_column == "distinct_id"
        assert result.target_column is None

    def test_record_join_appends_reasoning_on_repeat(self) -> None:
        params = RecordJoinParams(
            team_id=self.team.pk,
            source_table="events",
            target_table="persons",
            source_column="distinct_id",
            target_column=None,
            note="distinct_id is the person link",
            attribution="[@alice 2026-05-14]",
        )
        CatalogAPI.record_join(self.team, params)
        second = RecordJoinParams(
            team_id=self.team.pk,
            source_table="events",
            target_table="persons",
            source_column="distinct_id",
            target_column=None,
            note="overrides apply when person_overrides has a newer mapping",
            attribution="[@bob 2026-05-15]",
        )
        result = CatalogAPI.record_join(self.team, second)
        assert result.reasoning == (
            "[@alice 2026-05-14] distinct_id is the person link\n"
            "[@bob 2026-05-15] overrides apply when person_overrides has a newer mapping"
        )
        # Idempotent on edge tuple — single CatalogRelationship row.
        assert CatalogRelationship.objects.filter(team=self.team).count() == 1

    def test_record_join_upserts_both_nodes_and_columns(self) -> None:
        CatalogAPI.record_join(
            self.team,
            RecordJoinParams(
                team_id=self.team.pk,
                source_table="events",
                target_table="persons",
                source_column="distinct_id",
                target_column="id",
                note="primary person link",
                attribution="[@alice 2026-05-14]",
            ),
        )
        assert CatalogNode.objects.filter(team=self.team, name="events").exists()
        assert CatalogNode.objects.filter(team=self.team, name="persons").exists()
        assert CatalogColumn.objects.filter(team=self.team, node__name="events", name="distinct_id").exists()
        assert CatalogColumn.objects.filter(team=self.team, node__name="persons", name="id").exists()


class TestCatalogAPIGetNodeContext(BaseTest):
    """Read-side helper used by read_data / execute_sql to inject catalog context into tool output."""

    def test_returns_none_for_unknown_table(self) -> None:
        assert CatalogAPI.get_node_context(self.team, "definitely_not_a_real_table_zzz") is None

    def test_returns_none_when_no_catalog_node_for_known_table(self) -> None:
        # `events` resolves via HogQL but the catalog has no row for it yet.
        assert CatalogAPI.get_node_context(self.team, "events") is None

    def test_returns_descriptions_and_joins(self) -> None:
        # Seed an annotated node + column.
        CatalogAPI.append_node_note(
            self.team,
            AppendNodeNoteParams(
                team_id=self.team.pk,
                table_name="events",
                note="excludes staging traffic",
                attribution="[@alice 2026-05-14]",
            ),
        )
        CatalogAPI.append_column_note(
            self.team,
            AppendColumnNoteParams(
                team_id=self.team.pk,
                table_name="events",
                column_name="timestamp",
                note="UTC",
                attribution="[@alice 2026-05-14]",
            ),
        )
        # Seed a join edge.
        CatalogAPI.record_join(
            self.team,
            RecordJoinParams(
                team_id=self.team.pk,
                source_table="events",
                target_table="persons",
                source_column="distinct_id",
                target_column=None,
                note="events.distinct_id maps to a person",
                attribution="[@alice 2026-05-14]",
            ),
        )

        ctx = CatalogAPI.get_node_context(self.team, "events")
        assert ctx is not None
        assert ctx.kind == CatalogNode.Kind.POSTHOG_TABLE
        assert ctx.name == "events"
        assert ctx.description == "[@alice 2026-05-14] excludes staging traffic"
        descriptions_by_col = {c.name: c.description for c in ctx.columns}
        assert descriptions_by_col["timestamp"] == "[@alice 2026-05-14] UTC"
        assert len(ctx.outgoing_joins) == 1
        outgoing = ctx.outgoing_joins[0]
        assert outgoing.other_table == "persons"
        assert outgoing.self_column == "distinct_id"
        assert outgoing.kind == CatalogRelationship.Kind.DECLARED_JOIN
        assert "events.distinct_id maps to a person" in outgoing.reasoning
        # No incoming edges (target was persons, not events).
        assert ctx.incoming_joins == ()

    def test_excludes_rejected_joins(self) -> None:
        edge = CatalogAPI.record_join(
            self.team,
            RecordJoinParams(
                team_id=self.team.pk,
                source_table="events",
                target_table="persons",
                source_column="distinct_id",
                target_column=None,
                note="rejected later",
                attribution="[@alice 2026-05-14]",
            ),
        )
        CatalogAPI.update_relationship(
            UpdateRelationshipParams(
                team_id=self.team.pk,
                relationship_id=edge.id,
                status=CatalogRelationship.Status.REJECTED,
            )
        )
        ctx = CatalogAPI.get_node_context(self.team, "events")
        assert ctx is not None
        assert ctx.outgoing_joins == ()
