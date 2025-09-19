from posthog.test.base import BaseTest

from parameterized import parameterized

from posthog.schema import EventPropertyFilter, PropertyOperator

from posthog.hogql import ast

from posthog.models import EventProperty
from posthog.session_recordings.queries.sub_queries.events_subquery import ReplayFiltersEventsSubQuery
from posthog.types import AnyPropertyFilter


class TestWithTeamEventsAdded(BaseTest):
    @parameterized.expand(
        [
            (
                "event_property_filter_no_events",
                EventPropertyFilter(key="$browser", operator=PropertyOperator.EXACT, value="Chrome"),
                "$browser",
                ["$pageview", "$pageleave"],
                ast.Or(
                    exprs=[
                        ast.And(
                            exprs=[
                                ast.CompareOperation(
                                    op=ast.CompareOperationOp.Eq,
                                    left=ast.Field(chain=["events", "event"]),
                                    right=ast.Constant(value="$pageview"),
                                ),
                                ast.CompareOperation(
                                    op=ast.CompareOperationOp.Eq,
                                    left=ast.Field(chain=["events", "properties", "$browser"]),
                                    right=ast.Constant(value="Chrome"),
                                ),
                            ]
                        ),
                        ast.And(
                            exprs=[
                                ast.CompareOperation(
                                    op=ast.CompareOperationOp.Eq,
                                    left=ast.Field(chain=["events", "event"]),
                                    right=ast.Constant(value="$pageleave"),
                                ),
                                ast.CompareOperation(
                                    op=ast.CompareOperationOp.Eq,
                                    left=ast.Field(chain=["events", "properties", "$browser"]),
                                    right=ast.Constant(value="Chrome"),
                                ),
                            ]
                        ),
                    ]
                ),
            )
        ]
    )
    def test_with_team_events_added_basic_cases(
        self,
        _name: str,
        input_filter: AnyPropertyFilter,
        property_to_create: str,
        events_to_create: list[str],
        expected_filter: ast.Expr,
    ):
        for events in events_to_create:
            EventProperty.objects.create(team=self.team, event=events, property=property_to_create)

        result = ReplayFiltersEventsSubQuery.with_team_events_added(input_filter, self.team)

        assert result == expected_filter
