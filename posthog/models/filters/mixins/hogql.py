from typing import Dict

from posthog.hogql.hogql import HogQLContext
from posthog.models.filters.mixins.utils import cached_property


class HogQLParamMixin:
    kwargs: Dict

    @cached_property
    def hogql_context(self) -> HogQLContext:
        team = self.kwargs.get("team")
        context = self.kwargs.get(
            "hogql_context", HogQLContext(within_non_hogql_query=True, team_id=team.pk if team else None)
        )
        if team:
            context.person_on_events_mode = self.kwargs["team"].person_on_events_mode
        return context
