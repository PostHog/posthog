from typing import Dict

from posthog.hogql.database import create_hogql_database
from posthog.hogql.hogql import HogQLContext
from posthog.models.filters.mixins.utils import cached_property


class HogQLParamMixin:
    kwargs: Dict

    @cached_property
    def hogql_context(self) -> HogQLContext:
        team = self.kwargs.get("team")
        context = self.kwargs.get(
            "hogql_context",
            HogQLContext(within_non_hogql_query=True, database=team.database if team else create_hogql_database(None)),
        )
        if team:
            context.using_person_on_events = team.person_on_events_querying_enabled
        return context
