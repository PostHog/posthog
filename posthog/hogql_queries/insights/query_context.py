from abc import ABC
from datetime import datetime
from typing import Optional, Protocol

from posthog.schema import HogQLQueryModifiers

from posthog.hogql.constants import LimitContext
from posthog.hogql.context import HogQLContext
from posthog.hogql.modifiers import create_default_modifiers_for_team
from posthog.hogql.timings import HogQLTimings

from posthog.models.team.team import Team
from posthog.models.user import User
from posthog.types import InsightQueryNode


class QueryContext(ABC):
    query: InsightQueryNode
    team: Team
    user: Optional[User]
    timings: HogQLTimings
    modifiers: HogQLQueryModifiers
    limit_context: LimitContext
    hogql_context: HogQLContext
    now: datetime

    def __init__(
        self,
        query: InsightQueryNode,
        team: Team,
        timings: Optional[HogQLTimings] = None,
        modifiers: Optional[HogQLQueryModifiers] = None,
        limit_context: Optional[LimitContext] = None,
        now: Optional[datetime] = None,
        user: Optional[User] = None,
    ):
        self.query = query
        self.team = team
        self.user = user
        self.timings = timings or HogQLTimings()
        self.limit_context = limit_context or LimitContext.QUERY
        self.modifiers = create_default_modifiers_for_team(team, modifiers)
        self.hogql_context = HogQLContext(
            team_id=self.team.pk,
            enable_select_queries=True,
            timings=self.timings,
            modifiers=self.modifiers,
            user=user,
        )
        self.now = now or datetime.now()


class QueryContextProtocol(Protocol):
    context: QueryContext
