from posthog.test.base import BaseTest
from unittest.mock import MagicMock, patch

from django.db import IntegrityError

from parameterized import parameterized
from rest_framework.exceptions import ValidationError

from posthog.constants import AvailableFeature

from products.access_control.backend.models.access_control import AccessControl
from products.data_catalog.backend.facade.enums import CreatedSource, MetricStatus
from products.data_catalog.backend.logic import metrics
from products.data_catalog.backend.logic.drift import compute_drift
from products.data_catalog.backend.logic.exceptions import MetricDrifted, SourceInsightUnavailable
from products.data_catalog.backend.logic.metrics import (
    approve_metric,
    approved_metric_names_for_team,
    refresh_metric_from_insight,
    soft_delete_metric,
    update_metric,
    upsert_metric,
)
from products.data_catalog.backend.logic.validation import MAX_DESCRIPTION_LENGTH, validate_metric_definition
from products.data_catalog.backend.models import Metric
from products.product_analytics.backend.facade.models import Insight

_HOGQL_A = {"kind": "HogQLQuery", "query": "select count() from events"}
_HOGQL_B = {"kind": "HogQLQuery", "query": "select count() from persons"}


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

    def test_upsert_after_delete_creates_fresh_metric(self) -> None:
        metric = self._upsert("mrr", definition=_HOGQL_A)
        soft_delete_metric(metric)

        fresh = self._upsert("mrr", description="fresh")
        assert fresh.id != metric.id
        assert fresh.status == MetricStatus.PROPOSED
        assert fresh.definition is None
        metric.refresh_from_db()
        assert metric.deleted is True

    @parameterized.expand([("bad name",), ("1leading_digit",), ("has-dash",), ("",)])
    def test_rejects_invalid_names(self, name: str) -> None:
        with self.assertRaises(ValidationError):
            self._upsert(name)

    def test_description_capped_at_max_length(self) -> None:
        self._upsert("mrr", description="x" * MAX_DESCRIPTION_LENGTH)
        with self.assertRaises(ValidationError) as ctx:
            self._upsert("arr", description="x" * (MAX_DESCRIPTION_LENGTH + 1))
        assert "description" in ctx.exception.detail

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

    def test_rename_resets_approval(self) -> None:
        # Agents pick a metric by matching its name, so moving an approved definition under a new
        # name needs a fresh review. Catalog write access alone must not rebind an approved handle.
        metric = upsert_metric(team=self.team, user=self.user, name="mrr", description="v1")
        metric = approve_metric(metric, self.user)

        renamed = update_metric(metric, team=self.team, user=self.user, name="arr")
        assert renamed.name == "arr"
        assert renamed.status == MetricStatus.PROPOSED
        assert renamed.approved_by_id is None
        assert renamed.approved_at is None

    @parameterized.expand([("bad name",), ("1leading_digit",), ("has-dash",), ("",)])
    def test_rename_rejects_invalid_names(self, name: str) -> None:
        metric = upsert_metric(team=self.team, user=self.user, name="mrr", description="v1")
        with self.assertRaises(ValidationError):
            update_metric(metric, team=self.team, user=self.user, name=name)

    def test_rename_rejects_live_taken_name(self) -> None:
        upsert_metric(team=self.team, user=self.user, name="arr", description="taken")
        metric = upsert_metric(team=self.team, user=self.user, name="mrr", description="v1")
        with self.assertRaises(ValidationError) as ctx:
            update_metric(metric, team=self.team, user=self.user, name="arr")
        assert "name" in ctx.exception.detail

    def test_rename_to_soft_deleted_name_succeeds(self) -> None:
        tombstone = upsert_metric(team=self.team, user=self.user, name="arr", description="old")
        soft_delete_metric(tombstone)
        metric = upsert_metric(team=self.team, user=self.user, name="mrr", description="v1")

        renamed = update_metric(metric, team=self.team, user=self.user, name="arr")
        assert renamed.name == "arr"
        assert renamed.id == metric.id

    def test_update_rejects_overlong_description(self) -> None:
        metric = upsert_metric(team=self.team, user=self.user, name="mrr", description="v1")
        with self.assertRaises(ValidationError) as ctx:
            update_metric(metric, team=self.team, user=self.user, description="x" * (MAX_DESCRIPTION_LENGTH + 1))
        assert "description" in ctx.exception.detail

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
    @parameterized.expand(
        [
            ("plain", "select count() from events", ["events"]),
            (
                "cte_excluded",
                "with monthly as (select count() as c from events) select c from monthly join persons on 1 = 1",
                ["events", "persons"],
            ),
            (
                "cte_shadowing_real_table",
                "with events as (select uuid from events) select uuid from events",
                ["events"],
            ),
            (
                "join_constraint_subquery",
                "select count() from persons join groups on persons.id in (select person_id from events)",
                ["events", "groups", "persons"],
            ),
        ]
    )
    def test_valid_hogql_extracts_referenced_tables(self, _name: str, query: str, expected: list[str]) -> None:
        _, tables = validate_metric_definition({"kind": "HogQLQuery", "query": query}, self.team, self.user)
        assert tables == expected

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


class TestCreateFromInsight(BaseTest):
    def _insight(self, query: dict | None = None) -> Insight:
        return Insight.objects.create(team=self.team, created_by=self.user, query=query or _HOGQL_A)

    def test_snapshots_query_and_is_not_drifted(self) -> None:
        insight = self._insight()
        metric = upsert_metric(
            team=self.team, user=self.user, name="mrr", description="d", source_insight_short_id=insight.short_id
        )
        assert metric.definition is not None
        assert metric.definition["kind"] == "HogQLQuery"
        assert metric.source_insight_short_id == insight.short_id
        assert metric.source_insight_query_hash
        assert compute_drift([metric])[metric.id] is False

    def test_definition_and_source_are_mutually_exclusive(self) -> None:
        insight = self._insight()
        with self.assertRaises(ValidationError):
            upsert_metric(
                team=self.team,
                user=self.user,
                name="mrr",
                description="d",
                definition=_HOGQL_A,
                source_insight_short_id=insight.short_id,
            )

    def test_missing_insight_rejected(self) -> None:
        with self.assertRaises(ValidationError):
            upsert_metric(team=self.team, user=self.user, name="mrr", description="d", source_insight_short_id="nope")

    def test_create_from_insight_requires_viewer_access(self) -> None:
        # Catalog write access must not let a user snapshot an insight they can't view — that would
        # exfiltrate a restricted insight's query into the metric definition.
        insight = self._insight()
        with patch(
            "products.access_control.backend.facade.user_access_control.UserAccessControl.check_access_level_for_object",
            side_effect=lambda obj=None, *a, **k: type(obj).__name__ != "Insight",
        ):
            with self.assertRaises(ValidationError):
                upsert_metric(
                    team=self.team,
                    user=self.user,
                    name="mrr",
                    description="d",
                    source_insight_short_id=insight.short_id,
                )

    def test_reordered_insight_query_is_not_drift(self) -> None:
        insight = self._insight(query={"kind": "HogQLQuery", "query": "select 1"})
        metric = upsert_metric(
            team=self.team, user=self.user, name="mrr", description="d", source_insight_short_id=insight.short_id
        )
        # Same query, keys reordered: canonicalization (sort_keys + upgrade) must not read as drift.
        Insight.objects.filter(pk=insight.pk).update(query={"query": "select 1", "kind": "HogQLQuery"})
        assert compute_drift([metric])[metric.id] is False


class TestApproveMetric(BaseTest):
    def _insight(self, query: dict | None = None) -> Insight:
        return Insight.objects.create(team=self.team, created_by=self.user, query=query or _HOGQL_A)

    def test_approve_sets_status_and_approver(self) -> None:
        metric = upsert_metric(team=self.team, user=self.user, name="mrr", description="d", definition=_HOGQL_A)
        approved = approve_metric(metric, self.user)
        assert approved.status == MetricStatus.APPROVED
        assert approved.approved_by_id == self.user.id

    def test_approve_is_idempotent(self) -> None:
        metric = upsert_metric(team=self.team, user=self.user, name="mrr", description="d", definition=_HOGQL_A)
        approve_metric(metric, self.user)
        again = approve_metric(metric, self.user)
        assert again.status == MetricStatus.APPROVED

    def test_approve_blocked_while_drifted(self) -> None:
        insight = self._insight()
        metric = upsert_metric(
            team=self.team, user=self.user, name="mrr", description="d", source_insight_short_id=insight.short_id
        )
        Insight.objects.filter(pk=insight.pk).update(query=_HOGQL_B)
        with self.assertRaises(MetricDrifted):
            approve_metric(metric, self.user)

    def test_reapprove_of_drifted_approved_metric_raises(self) -> None:
        insight = self._insight()
        metric = upsert_metric(
            team=self.team, user=self.user, name="mrr", description="d", source_insight_short_id=insight.short_id
        )
        approve_metric(metric, self.user)
        Insight.objects.filter(pk=insight.pk).update(query=_HOGQL_B)
        with self.assertRaises(MetricDrifted):
            approve_metric(metric, self.user)

    def test_approve_checks_drift_on_the_current_row_not_the_loaded_instance(self) -> None:
        metric = upsert_metric(
            team=self.team,
            user=self.user,
            name="mrr",
            description="d",
            source_insight_short_id=self._insight().short_id,
        )
        stale = Metric.objects.for_team(self.team.id).get(pk=metric.pk)
        insight_b = self._insight(query=_HOGQL_B)
        update_metric(metric, team=self.team, user=self.user, source_insight_short_id=insight_b.short_id)
        Insight.objects.filter(pk=insight_b.pk).update(query={"kind": "HogQLQuery", "query": "select 1"})

        with self.assertRaises(MetricDrifted):
            approve_metric(stale, self.user)


class TestBulkRenameRace(BaseTest):
    @parameterized.expand(
        [
            ("approve", metrics.bulk_approve_metrics, MetricStatus.PROPOSED),
            ("delete", metrics.bulk_soft_delete_metrics, MetricStatus.PROPOSED),
        ]
    )
    def test_bulk_skips_a_metric_renamed_since_resolution(self, _name: str, bulk_action, expected_status: str) -> None:
        metric = upsert_metric(team=self.team, user=self.user, name="mrr", description="d", definition=_HOGQL_A)
        # The caller resolved "mrr" to this row; another writer renames it before the batch locks it.
        Metric.objects.for_team(self.team.id).filter(pk=metric.pk).update(name="arr")

        acted, skipped = bulk_action([metric], self.user)

        assert acted == []
        assert [(skip.name, skip.reason) for skip in skipped] == [("mrr", metrics.BULK_SKIP_NOT_FOUND)]
        current = Metric.objects.for_team(self.team.id).get(pk=metric.pk)
        assert current.status == expected_status
        assert current.deleted is False


class TestRefreshFromInsight(BaseTest):
    def _insight(self, query: dict | None = None) -> Insight:
        return Insight.objects.create(team=self.team, created_by=self.user, query=query or _HOGQL_A)

    def test_refresh_resnapshots_and_resets_approval(self) -> None:
        insight = self._insight()
        metric = upsert_metric(
            team=self.team, user=self.user, name="mrr", description="d", source_insight_short_id=insight.short_id
        )
        approve_metric(metric, self.user)
        Insight.objects.filter(pk=insight.pk).update(query=_HOGQL_B)

        refreshed = refresh_metric_from_insight(metric, self.user)
        assert refreshed.status == MetricStatus.PROPOSED
        assert refreshed.definition is not None
        assert "persons" in refreshed.definition["query"]
        assert compute_drift([refreshed])[refreshed.id] is False

    def test_refresh_deleted_insight_errors(self) -> None:
        insight = self._insight()
        metric = upsert_metric(
            team=self.team, user=self.user, name="mrr", description="d", source_insight_short_id=insight.short_id
        )
        Insight.objects.filter(pk=insight.pk).update(deleted=True)
        with self.assertRaises(SourceInsightUnavailable):
            refresh_metric_from_insight(metric, self.user)

    def test_refresh_requires_viewer_access(self) -> None:
        # Losing viewer access to the linked insight must block re-snapshotting it.
        insight = self._insight()
        metric = upsert_metric(
            team=self.team, user=self.user, name="mrr", description="d", source_insight_short_id=insight.short_id
        )
        with patch(
            "products.access_control.backend.facade.user_access_control.UserAccessControl.check_access_level_for_object",
            side_effect=lambda obj=None, *a, **k: type(obj).__name__ != "Insight",
        ):
            with self.assertRaises(ValidationError):
                refresh_metric_from_insight(metric, self.user)


class TestUpdateResetsApproval(BaseTest):
    def test_editing_definition_resets_approval(self) -> None:
        metric = upsert_metric(team=self.team, user=self.user, name="mrr", description="d", definition=_HOGQL_A)
        approve_metric(metric, self.user)
        updated = update_metric(metric, team=self.team, user=self.user, definition=_HOGQL_B)
        assert updated.status == MetricStatus.PROPOSED
        assert updated.approved_by_id is None

    def test_cosmetic_edit_keeps_approval(self) -> None:
        metric = upsert_metric(team=self.team, user=self.user, name="mrr", description="d", definition=_HOGQL_A)
        approve_metric(metric, self.user)
        updated = update_metric(metric, team=self.team, user=self.user, display_name="MRR")
        assert updated.status == MetricStatus.APPROVED

    @parameterized.expand(
        [
            ("description", {"description": "a materially different meaning"}),
            ("unit", {"unit": "percent"}),
        ]
    )
    def test_semantic_edit_resets_approval(self, _name: str, edit: dict) -> None:
        # description and unit carry the metric's reviewed meaning (for a definition-less metric the
        # description *is* the definition), so editing them with catalog write access must re-open review.
        metric = upsert_metric(team=self.team, user=self.user, name="mrr", description="d", unit="usd")
        approve_metric(metric, self.user)
        updated = update_metric(metric, team=self.team, user=self.user, **edit)
        assert updated.status == MetricStatus.PROPOSED
        assert updated.approved_by_id is None

    def test_refine_definition_resets_approval(self) -> None:
        metric = upsert_metric(team=self.team, user=self.user, name="mrr", description="d", definition=_HOGQL_A)
        approve_metric(metric, self.user)
        refined = upsert_metric(team=self.team, user=self.user, name="mrr", description="d", definition=_HOGQL_B)
        assert refined.status == MetricStatus.PROPOSED
        assert refined.approved_by_id is None

    def test_refine_cosmetic_change_keeps_approval(self) -> None:
        metric = upsert_metric(team=self.team, user=self.user, name="mrr", description="d", definition=_HOGQL_A)
        approve_metric(metric, self.user)
        refined = upsert_metric(team=self.team, user=self.user, name="mrr", description="d", display_name="MRR")
        assert refined.status == MetricStatus.APPROVED

    def test_refine_description_change_resets_approval(self) -> None:
        # A refine that omits the definition but rewrites the description changes what a
        # definition-less metric means, so its approval must not carry over.
        metric = upsert_metric(team=self.team, user=self.user, name="mrr", description="d")
        approve_metric(metric, self.user)
        refined = upsert_metric(team=self.team, user=self.user, name="mrr", description="a different meaning")
        assert refined.status == MetricStatus.PROPOSED
        assert refined.approved_by_id is None

    def test_stale_update_after_approve_still_resets_approval(self) -> None:
        metric = upsert_metric(team=self.team, user=self.user, name="mrr", description="d", definition=_HOGQL_A)
        stale = Metric.objects.for_team(self.team.id).get(pk=metric.pk)
        approve_metric(metric, self.user)

        update_metric(stale, team=self.team, user=self.user, definition=_HOGQL_B)

        metric.refresh_from_db()
        assert metric.status == MetricStatus.PROPOSED
        assert metric.approved_by_id is None
        assert metric.definition is not None
        assert "persons" in metric.definition["query"]


class TestUpdateInsightLink(BaseTest):
    def _insight(self, query: dict | None = None) -> Insight:
        return Insight.objects.create(team=self.team, created_by=self.user, query=query or _HOGQL_A)

    @parameterized.expand(
        [
            ("drifted", True, MetricStatus.PROPOSED),
            ("in_sync", False, MetricStatus.APPROVED),
        ]
    )
    def test_unlink_resets_approval_only_while_drifted(self, _name: str, drifted: bool, expected: str) -> None:
        # Unlinking a drifted approved metric would erase the drift signal that flags the approval
        # as stale, so it must re-open review; unlinking an in-sync metric keeps the blessing.
        insight = self._insight()
        metric = upsert_metric(
            team=self.team, user=self.user, name="mrr", description="d", source_insight_short_id=insight.short_id
        )
        approve_metric(metric, self.user)
        if drifted:
            Insight.objects.filter(pk=insight.pk).update(query=_HOGQL_B)

        updated = update_metric(metric, team=self.team, user=self.user, source_insight_short_id=None)

        assert updated.source_insight_short_id is None
        assert updated.status == expected

    def test_relink_to_new_insight_snapshots_and_resets_approval(self) -> None:
        metric = upsert_metric(
            team=self.team,
            user=self.user,
            name="mrr",
            description="d",
            source_insight_short_id=self._insight().short_id,
        )
        approve_metric(metric, self.user)
        insight_b = self._insight(query=_HOGQL_B)

        updated = update_metric(metric, team=self.team, user=self.user, source_insight_short_id=insight_b.short_id)

        assert updated.status == MetricStatus.PROPOSED
        assert updated.source_insight_short_id == insight_b.short_id
        assert updated.definition is not None
        assert "persons" in updated.definition["query"]
        assert compute_drift([updated])[updated.id] is False

    @parameterized.expand(["update", "refine"])
    def test_definition_edit_unlinks_source_insight(self, path: str) -> None:
        metric = upsert_metric(
            team=self.team,
            user=self.user,
            name="mrr",
            description="d",
            source_insight_short_id=self._insight().short_id,
        )
        if path == "update":
            edited = update_metric(metric, team=self.team, user=self.user, definition=_HOGQL_B)
        else:
            edited = upsert_metric(team=self.team, user=self.user, name="mrr", description="d", definition=_HOGQL_B)

        assert edited.source_insight_short_id is None
        assert edited.source_insight_query_hash is None

    def test_definition_and_source_are_mutually_exclusive_on_update(self) -> None:
        metric = upsert_metric(team=self.team, user=self.user, name="mrr", description="d", definition=_HOGQL_A)
        with self.assertRaises(ValidationError):
            update_metric(
                metric,
                team=self.team,
                user=self.user,
                definition=_HOGQL_A,
                source_insight_short_id=self._insight().short_id,
            )


class TestApprovedMetricSummaries(BaseTest):
    def test_only_approved_non_drifted_metric_names_are_listed(self) -> None:
        approved = upsert_metric(
            team=self.team,
            user=self.user,
            name="mrr",
            display_name="MRR",
            description="Monthly recurring revenue",
            unit="usd",
            definition=_HOGQL_A,
        )
        approve_metric(approved, self.user)

        upsert_metric(team=self.team, user=self.user, name="proposed_only", description="d", definition=_HOGQL_A)

        removed = upsert_metric(team=self.team, user=self.user, name="removed", description="d", definition=_HOGQL_A)
        approve_metric(removed, self.user)
        soft_delete_metric(removed, self.user)

        insight = Insight.objects.create(team=self.team, created_by=self.user, query=_HOGQL_A)
        drifted = upsert_metric(
            team=self.team, user=self.user, name="drifted", description="d", source_insight_short_id=insight.short_id
        )
        approve_metric(drifted, self.user)
        Insight.objects.filter(pk=insight.pk).update(query=_HOGQL_B)

        assert approved_metric_names_for_team(self.team, self.user) == ["mrr"]

    def test_names_are_withheld_from_a_caller_without_data_catalog_access(self) -> None:
        approved = upsert_metric(team=self.team, user=self.user, name="mrr", description="d", definition=_HOGQL_A)
        approve_metric(approved, self.user)
        AccessControl.objects.create(team=self.team, resource="data_catalog", access_level="none")
        self.organization.available_product_features = [{"key": AvailableFeature.ACCESS_CONTROL, "name": "access"}]
        self.organization.save()

        assert approved_metric_names_for_team(self.team, self.user) == []
        assert approved_metric_names_for_team(self.team, None) == ["mrr"]
