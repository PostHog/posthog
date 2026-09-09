from uuid import uuid4

from posthog.test.base import APIBaseTest

from parameterized import parameterized

from posthog.models.team import Team

from products.data_catalog.backend.facade.api import get_hogql_metric_definition
from products.data_catalog.backend.facade.contracts import HogQLMetricDefinition
from products.data_catalog.backend.logic.metric_reads import (
    get_metric_summary,
    live_metric_summaries,
    metric_reads_for_ids,
)
from products.data_catalog.backend.logic.metrics import upsert_metric

_HOGQL = {"kind": "HogQLQuery", "query": "select count() from events"}
_HOGQL_WITH_VALUES = {
    "kind": "HogQLQuery",
    "query": "SELECT count() FROM events WHERE event = {event_name}",
    "values": {"event_name": "signup"},
}
_TRENDS = {"kind": "TrendsQuery", "series": [{"kind": "EventsNode", "event": "$pageview"}]}
_FUNNELS = {"kind": "FunnelsQuery", "series": [{"kind": "EventsNode", "event": "signup"}]}
_MARKDOWN = {"kind": "MarkdownDefinition", "markdown": "1. Count activated users."}


class TestMetricReads(APIBaseTest):
    @parameterized.expand(
        [
            ("saved_values", _HOGQL_WITH_VALUES, {"event_name": "signup"}),
            ("absent_values", _HOGQL, {}),
            ("null_values", {**_HOGQL, "values": None}, {}),
        ]
    )
    def test_get_hogql_metric_definition_returns_saved_query_and_parameters(
        self, _name: str, definition: dict, expected_values: dict
    ) -> None:
        metric = upsert_metric(
            team=self.team,
            user=self.user,
            name="signup_count",
            description="Counts signup events",
            definition=definition,
        )

        with self.assertNumQueries(2):
            reads = metric_reads_for_ids(self.team.id, [metric.id, metric.id, uuid4()])
        assert set(reads) == {metric.id}
        assert reads[metric.id].summary.name == metric.name
        assert reads[metric.id].hogql_definition == HogQLMetricDefinition(
            query=definition["query"], values=expected_values
        )
        read = get_hogql_metric_definition(self.team.id, metric.id)

        assert read == HogQLMetricDefinition(query=definition["query"], values=expected_values)

    @parameterized.expand(
        [
            ("trends", "trends"),
            ("funnels", "funnels"),
            ("markdown", "markdown"),
            ("definitionless", "definitionless"),
            ("deleted", "deleted"),
            ("missing", "missing"),
            ("another_team", "another_team"),
            ("non_dict_values", "non_dict_values"),
        ]
    )
    def test_get_hogql_metric_definition_rejects_non_live_hogql_metrics(self, _name: str, case: str) -> None:
        metrics = {
            "trends": upsert_metric(
                team=self.team, user=self.user, name="trends_metric", description="Trends metric", definition=_TRENDS
            ),
            "funnels": upsert_metric(
                team=self.team,
                user=self.user,
                name="funnels_metric",
                description="Funnels metric",
                definition=_FUNNELS,
            ),
            "markdown": upsert_metric(
                team=self.team,
                user=self.user,
                name="markdown_metric",
                description="Markdown metric",
                definition=_MARKDOWN,
            ),
            "definitionless": upsert_metric(
                team=self.team, user=self.user, name="stub_metric", description="Stub metric"
            ),
            "deleted": upsert_metric(
                team=self.team,
                user=self.user,
                name="deleted_metric",
                description="Deleted metric",
                definition=_HOGQL,
            ),
            "non_dict_values": upsert_metric(
                team=self.team,
                user=self.user,
                name="malformed_metric",
                description="Metric whose stored parameters are not an object",
                definition=_HOGQL,
            ),
        }
        type(metrics["deleted"]).objects.for_team(self.team.id).filter(id=metrics["deleted"].id).update(deleted=True)
        type(metrics["non_dict_values"]).objects.for_team(self.team.id).filter(id=metrics["non_dict_values"].id).update(
            definition={**_HOGQL, "values": []}
        )
        other_team = Team.objects.create_with_data(
            organization=self.organization, initiating_user=self.user, name="Other"
        )
        metrics["another_team"] = upsert_metric(
            team=other_team,
            user=self.user,
            name="other_team_metric",
            description="Other team's metric",
            definition=_HOGQL,
        )

        metric_id = uuid4() if case == "missing" else metrics[case].id

        assert get_hogql_metric_definition(self.team.id, metric_id) is None
        with self.assertNumQueries(2):
            reads = metric_reads_for_ids(self.team.id, [metric_id])
        if case in {"missing", "deleted", "another_team"}:
            assert reads == {}
        else:
            assert reads[metric_id].hogql_definition is None

    def test_summary_exposes_lifecycle_and_navigation_fields(self) -> None:
        metric = upsert_metric(
            team=self.team,
            user=self.user,
            name="revenue",
            display_name="Revenue",
            description="Recognized revenue",
            definition=_HOGQL,
        )

        summary = get_metric_summary(self.team.id, metric.id)

        assert summary is not None
        assert summary.id == metric.id
        assert summary.name == "revenue"
        assert summary.display_name == "Revenue"
        assert summary.definition_kind == "HogQLQuery"
        assert summary.referenced_table_names == ["events"]

    def test_live_summaries_are_team_scoped_and_exclude_deleted_metrics(self) -> None:
        trend = upsert_metric(
            team=self.team,
            user=self.user,
            name="signups",
            description="New signups",
            definition=_TRENDS,
        )
        markdown = upsert_metric(
            team=self.team,
            user=self.user,
            name="activation",
            description="Activated users",
            definition=_MARKDOWN,
        )
        deleted = upsert_metric(
            team=self.team,
            user=self.user,
            name="deleted_metric",
            description="Deleted metric",
            definition=_HOGQL,
        )
        type(deleted).objects.for_team(self.team.id).filter(id=deleted.id).update(deleted=True)

        summaries = live_metric_summaries(self.team.id)

        assert [summary.id for summary in summaries] == [trend.id, markdown.id]
        assert get_metric_summary(self.team.id, deleted.id) is None
