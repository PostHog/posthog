from posthog.hogql import ast
from posthog.hogql.parser import parse_expr

from posthog.hogql_queries.insights.funnels.funnel_unordered import FunnelUnordered


class FunnelUnorderedActors(FunnelUnordered):
    def _get_funnel_person_step_events(self) -> list[ast.Expr]:
        # Unordered funnels does not support matching events (and thereby recordings),
        # but it simplifies the logic if we return an empty array for matching events
        if (
            hasattr(self.context, "actorsQuery")
            and self.context.actorsQuery is not None
            and self.context.actorsQuery.includeRecordings
        ):
            return [parse_expr("array() as matching_events")]
        return []
