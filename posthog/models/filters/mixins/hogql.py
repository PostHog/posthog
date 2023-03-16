from functools import cached_property
from typing import Dict

from posthog.hogql.hogql import HogQLContext


class HogQLParamMixin:
    kwargs: Dict

    @cached_property
    def hogql_context(self) -> HogQLContext:
        context = self.kwargs.get("hogql_context", HogQLContext(within_non_hogql_query=True))
        if self.kwargs.get("team"):
            context.using_person_on_events = self.kwargs["team"].person_on_events_querying_enabled
        return context
