from typing import Any

from posthog.test.base import APIBaseTest, ClickhouseTestMixin, _create_event, flush_persons_and_events
from unittest.mock import patch

from django.contrib.auth.models import AnonymousUser
from django.test import override_settings

from parameterized import parameterized

from posthog.schema import DateRange, HogQLFilters, HogQLQueryModifiers, HogQLQueryResponse, PersonsOnEventsMode

from posthog.hogql import ast
from posthog.hogql.context import HogQLContext
from posthog.hogql.parser import parse_select
from posthog.hogql.property_access_types import RestrictedProperty
from posthog.hogql.query import HogQLQueryExecutor
from posthog.hogql.timings import HogQLTimings

from posthog.hogql_client.execute import execute_hogql_query
from posthog.synthetic_user import SyntheticUser

from products.access_control.backend.facade.user_access_control import UserAccessControl


class TestExecuteThroughRequest(ClickhouseTestMixin, APIBaseTest):
    def _run_events_query(self, timings: HogQLTimings) -> HogQLQueryResponse:
        with timings.measure("runner"):
            return execute_hogql_query(
                parse_select(
                    "select properties.index, properties.secret, {label} from events "
                    "where event = {event} and {filters} order by properties.index"
                ),
                self.team,
                user=self.user,
                user_access_control=UserAccessControl(self.user, self.team),
                placeholders={"label": ast.Constant(value="a"), "event": ast.Constant(value="through request")},
                filters=HogQLFilters(dateRange=DateRange(date_from="-1d")),
                modifiers=HogQLQueryModifiers(personsOnEventsMode=PersonsOnEventsMode.DISABLED),
                context=HogQLContext(
                    team_id=self.team.pk, restricted_properties={RestrictedProperty(name="secret", property_type=1)}
                ),
                timings=timings,
                pretty=False,
            )

    def test_gives_the_in_process_response(self) -> None:
        for index in range(2):
            _create_event(
                distinct_id="someone",
                event="through request",
                team=self.team,
                properties={"index": index, "secret": "hidden"},
            )
        flush_persons_and_events()
        in_process = self._run_events_query(HogQLTimings())
        timings = HogQLTimings()

        with (
            override_settings(HOGQL_EXECUTE_THROUGH_REQUEST=True),
            patch("posthog.hogql_service.execute.HogQLQueryExecutor", wraps=HogQLQueryExecutor) as executor,
        ):
            through_request = self._run_events_query(timings)

        assert in_process.results == [("0", None, "a"), ("1", None, "a")]
        assert through_request.model_dump(exclude={"timings"}) == in_process.model_dump(exclude={"timings"})
        served_team, served_user = executor.call_args.args[1], executor.call_args.kwargs["user"]
        assert (served_team, served_user) == (self.team, self.user) and served_team is not self.team
        assert "./runner/query" in timings.timings and "./query" not in timings.timings
        assert {timing.k for timing in through_request.timings or []} == timings.to_dict().keys()

    @parameterized.expand([("shared_link_viewer", AnonymousUser()), ("service_token", SyntheticUser)])
    @override_settings(HOGQL_EXECUTE_THROUGH_REQUEST=True)
    def test_refuses_a_principal_that_is_not_a_user_row(self, _name: str, principal: Any) -> None:
        user = principal(self.team, "token") if principal is SyntheticUser else principal

        with self.assertRaisesRegex(ValueError, "principal has no wire form"):
            execute_hogql_query("select 1", self.team, user=user)
