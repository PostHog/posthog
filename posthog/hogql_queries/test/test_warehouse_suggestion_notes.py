from uuid import UUID

from posthog.test.base import BaseTest
from unittest import mock

from parameterized import parameterized

from posthog.clickhouse.query_tagging import AccessMethod, Product, tags_context
from posthog.hogql_queries.query_runner import ExecutionMode
from posthog.hogql_queries.test.test_query_runner import (
    _calculate_recording_clickhouse_stats,
    _shared_link_user,
    setup_test_query_runner_class,
)

from products.warehouse_suggestions.backend.facade.contracts import WarehouseSuggestionNote
from products.warehouse_suggestions.backend.facade.enums import WarehouseSuggestionKind

FACADE = "products.warehouse_suggestions.backend.facade.api.suggestions_for_read_views"
REPORT = "posthog.hogql_queries.query_runner.report_user_or_team_action"
NOTE = WarehouseSuggestionNote(
    id=UUID("01a11171-0000-7000-8000-000000000001"),
    kind=WarehouseSuggestionKind.MATERIALIZE,
    view_name="orders",
    message="Materializing `orders` would save people about 40 minutes of waiting a month (estimated).",
    url="https://example.com/project/1/models/view-a?lookup=saved_query",
    can_act=True,
)


class TestWarehouseSuggestionNotes(BaseTest):
    def _run(self, user, *, execution_mode: ExecutionMode = ExecutionMode.CALCULATE_BLOCKING_ALWAYS):
        runner_class = setup_test_query_runner_class()
        runner = runner_class(query={"some_attr": "bla"}, team=self.team)
        with (
            mock.patch.object(
                runner_class, "_calculate", autospec=True, side_effect=_calculate_recording_clickhouse_stats
            ),
            mock.patch(REPORT) as report,
        ):
            response = runner.run(execution_mode=execution_mode, user=user)
        return response, report.call_args.args[1]

    @parameterized.expand(
        [
            ("personal api key", {"access_method": AccessMethod.PERSONAL_API_KEY}),
            ("posthog ai", {"product": Product.MAX_AI}),
        ]
    )
    def test_agent_gets_notes_on_the_fresh_run_and_none_on_the_cache_hit(self, _name: str, tags: dict) -> None:
        with tags_context(**tags), mock.patch(FACADE, return_value=[NOTE]) as facade:
            fresh, fresh_props = self._run(self.user)
            cached, _ = self._run(self.user, execution_mode=ExecutionMode.CACHE_ONLY_NEVER_CALCULATE)

        assert [note.message for note in fresh.warehouse_suggestions] == [NOTE.message]
        assert fresh_props["warehouse_suggestion_ids"] == [str(NOTE.id)]
        assert facade.call_args.args[2] == {"view-a"}
        assert cached.is_cached is True
        assert cached.warehouse_suggestions is None

    @parameterized.expand(
        [
            ("web app session", {}, False),
            ("shared link", {"access_method": AccessMethod.PERSONAL_API_KEY}, True),
            ("endpoint", {"access_method": AccessMethod.PERSONAL_API_KEY, "product": Product.ENDPOINTS}, False),
        ]
    )
    def test_non_agent_callers_get_no_notes(self, _name: str, tags: dict, shared_link: bool) -> None:
        user = _shared_link_user(self.team) if shared_link else self.user
        with tags_context(**tags), mock.patch(FACADE, return_value=[NOTE]) as facade:
            response, props = self._run(user)

        assert response.warehouse_suggestions is None
        assert props["warehouse_suggestions_skipped_reason"] == "not_agent"
        facade.assert_not_called()

    def test_a_failed_lookup_keeps_the_query_and_reports_it(self) -> None:
        with (
            tags_context(access_method=AccessMethod.PERSONAL_API_KEY),
            mock.patch(FACADE, side_effect=RuntimeError("suggestions unavailable")),
        ):
            response, props = self._run(self.user)

        assert response.results == []
        assert response.warehouse_suggestions is None
        assert props["warehouse_suggestions_skipped_reason"] == "failed"
