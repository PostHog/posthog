from typing import Optional
from posthog.hogql.constants import LimitContext
from posthog.hogql.context import HogQLContext
from posthog.hogql.modifiers import create_default_modifiers_for_team
from posthog.hogql.timings import HogQLTimings
from posthog.models.filters.mixins.utils import cached_property
from posthog.models.team.team import Team
from posthog.schema import FunnelsFilter, FunnelsQuery, HogQLQueryModifiers
from posthog.hogql_queries.utils.query_date_range import QueryDateRange
from datetime import datetime


class FunnelQueryContext:
    query: FunnelsQuery
    team: Team
    timings: HogQLTimings
    modifiers: HogQLQueryModifiers
    limit_context: LimitContext
    hogql_context: HogQLContext

    funnelsFilter: FunnelsFilter

    def __init__(
        self,
        query: FunnelsQuery,
        team: Team,
        timings: Optional[HogQLTimings] = None,
        modifiers: Optional[HogQLQueryModifiers] = None,
        limit_context: Optional[LimitContext] = None,
    ):
        self.query = query
        self.team = team
        self.timings = timings or HogQLTimings()
        self.limit_context = limit_context or LimitContext.QUERY
        self.modifiers = create_default_modifiers_for_team(team, modifiers)
        self.hogql_context = HogQLContext(
            team_id=self.team.pk,
            enable_select_queries=True,
            timings=self.timings,
            modifiers=self.modifiers,
        )

        self.funnelsFilter = self.query.funnelsFilter or FunnelsFilter()

    @cached_property
    def query_date_range(self):
        return QueryDateRange(
            date_range=self.query.dateRange,
            team=self.team,
            interval=self.query.interval,
            now=datetime.now(),
        )
