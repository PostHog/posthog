from uuid import UUID

from posthog.test.base import BaseTest
from unittest import mock

from django.test import SimpleTestCase

from parameterized import parameterized

from posthog.schema import TestBasicQueryResponse as TheTestBasicQueryResponse

from posthog.hogql.query_stats import get_active

from posthog.clickhouse.query_tagging import AccessMethod, Product, tags_context
from posthog.event_usage import EventSource
from posthog.hogql_queries.query_runner import ExecutionMode
from posthog.hogql_queries.test.test_query_runner import (
    _calculate_recording_clickhouse_stats,
    _shared_link_user,
    setup_test_query_runner_class,
)
from posthog.hogql_queries.warehouse_suggestion_notes import MAX_READ_VIEWS, CredentialAccess, credential_access

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
            ("mcp", {"source": EventSource.MCP}),
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
            ("personal api key script", {"access_method": AccessMethod.PERSONAL_API_KEY}, False),
            ("shared link", {"product": Product.MAX_AI}, True),
            ("endpoint", {"source": EventSource.MCP, "product": Product.ENDPOINTS}, False),
            ("cache warming", {"product": Product.MAX_AI, "trigger": "warmingV2"}, False),
        ]
    )
    def test_non_agent_callers_get_no_notes(self, _name: str, tags: dict, shared_link: bool) -> None:
        user = _shared_link_user(self.team) if shared_link else self.user
        with tags_context(**tags), mock.patch(FACADE, return_value=[NOTE]) as facade:
            response, props = self._run(user)

        assert response.warehouse_suggestions is None
        assert props["warehouse_suggestions_skipped_reason"] == "not_agent"
        facade.assert_not_called()

    @parameterized.expand(
        [
            ("web app session", {}, True),
            ("token with warehouse write scope", {"warehouse_suggestion_access": "write"}, True),
            ("token with warehouse read scope", {"warehouse_suggestion_access": "read"}, False),
        ]
    )
    def test_only_a_write_scope_lets_the_note_offer_actions(self, _name: str, tags: dict, can_write: bool) -> None:
        with tags_context(source=EventSource.MCP, **tags), mock.patch(FACADE, return_value=[NOTE]) as facade:
            self._run(self.user)

        assert facade.call_args.kwargs["can_write"] is can_write

    @parameterized.expand(
        [
            ("token without warehouse scope", {"warehouse_suggestion_access": "none"}),
            ("token the request never checked", {"access_method": AccessMethod.OAUTH}),
        ]
    )
    def test_a_token_without_warehouse_read_scope_gets_no_notes(self, _name: str, tags: dict) -> None:
        with tags_context(source=EventSource.MCP, **tags), mock.patch(FACADE, return_value=[NOTE]) as facade:
            response, props = self._run(self.user)

        assert response.warehouse_suggestions is None
        assert props["warehouse_suggestions_skipped_reason"] == "no_scope"
        facade.assert_not_called()

    @parameterized.expand(
        [
            ("failed lookup", {"side_effect": RuntimeError("suggestions unavailable")}, "failed"),
            ("flag off", {"return_value": None}, "flag_off"),
        ]
    )
    def test_a_lookup_without_notes_keeps_the_query_and_reports_why(
        self, _name: str, facade_behavior: dict, reason: str
    ) -> None:
        with tags_context(product=Product.MAX_AI), mock.patch(FACADE, **facade_behavior):
            response, props = self._run(self.user)

        assert response.results == []
        assert response.warehouse_suggestions is None
        assert props["warehouse_suggestions_skipped_reason"] == reason

    def test_too_many_views_skips_the_lookup(self) -> None:
        many_views = {f"view-{index}" for index in range(MAX_READ_VIEWS + 1)}

        def calculate_reading_many_views(_self):
            stats = get_active()
            assert stats is not None
            stats.add_reads(warehouse_table_ids=set(), saved_query_ids=many_views)
            return TheTestBasicQueryResponse(results=[])

        runner_class = setup_test_query_runner_class()
        runner = runner_class(query={"some_attr": "bla"}, team=self.team)
        with (
            tags_context(product=Product.MAX_AI),
            mock.patch(FACADE) as facade,
            mock.patch.object(runner_class, "_calculate", autospec=True, side_effect=calculate_reading_many_views),
            mock.patch(REPORT) as report,
        ):
            runner.run(execution_mode=ExecutionMode.CALCULATE_BLOCKING_ALWAYS, user=self.user)

        assert report.call_args.args[1]["warehouse_suggestions_skipped_reason"] == "too_many_views"
        facade.assert_not_called()


class TestCredentialAccess(SimpleTestCase):
    @parameterized.expand(
        [
            ("session", None, CredentialAccess.WRITE),
            ("all scopes", ["*"], CredentialAccess.WRITE),
            ("query only", ["query:read"], CredentialAccess.NONE),
            ("view read", ["query:read", "warehouse_view:read"], CredentialAccess.READ),
            ("warehouse read", ["warehouse_objects:read"], CredentialAccess.READ),
            ("view write", ["warehouse_view:write"], CredentialAccess.WRITE),
            ("table write only", ["warehouse_table:write"], CredentialAccess.NONE),
        ]
    )
    def test_matches_the_warehouse_suggestions_api_scopes(
        self, _name: str, scopes: list[str] | None, expected: CredentialAccess
    ) -> None:
        assert credential_access(scopes) == expected
