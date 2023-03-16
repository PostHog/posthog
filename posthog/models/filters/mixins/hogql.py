from typing import Dict

from posthog.hogql.hogql import HogQLContext
from posthog.models.filters.mixins.utils import cached_property


class HogQLParamMixin:
    kwargs: Dict

    @cached_property
    def hogql_context(self) -> HogQLContext:
        context = self.kwargs.get("hogql_context", HogQLContext(within_non_hogql_query=True))
        if self.kwargs.get("team"):
            context.person_on_events_mode = self.kwargs["team"].person_on_events_mode
        return context
