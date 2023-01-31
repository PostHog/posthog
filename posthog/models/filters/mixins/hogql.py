from typing import Dict

from posthog.hogql.hogql import HogQLContext
from posthog.models.filters.mixins.utils import cached_property


class HogQLParamMixin:
    kwargs: Dict

    @cached_property
    def hogql_context(self) -> HogQLContext:
        context = self.kwargs.get("hogql_context", HogQLContext())
        if self.kwargs.get("team"):
            context.using_person_on_events = self.kwargs["team"].person_on_events_querying_enabled
        return context
