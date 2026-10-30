from pydantic import ValidationError

from posthog.schema import (
    ActorsQuery,
    FunnelsActorsQuery,
    InsightActorsQuery,
    PathsV2ActorsQuery,
    StickinessActorsQuery,
    TrendsQuery,
)

from posthog.hogql import ast
from posthog.hogql.context import HogQLContext
from posthog.hogql.errors import QueryError

from posthog.hogql_queries.utils.breakdowns import BREAKDOWN_OTHER_STRING_LABEL


def matches_insight(node: ast.Call, context: HogQLContext, events_alias: str) -> ast.Expr:
    argument = node.args[0]
    if not isinstance(argument, ast.Constant) or not isinstance(argument.value, str):
        raise QueryError("matchesInsight expects a constant JSON actor query", node=node)
    if len(argument.value) > 100_000:
        raise QueryError("The insight selection is too large", node=node)
    try:
        query = ActorsQuery.model_validate_json(argument.value)
    except ValidationError as error:
        raise QueryError("Invalid insight actor query", node=node) from error
    if not isinstance(
        query.source, (InsightActorsQuery, FunnelsActorsQuery, StickinessActorsQuery, PathsV2ActorsQuery)
    ):
        raise QueryError("matchesInsight requires a product analytics datapoint", node=node)
    if context.team_id is None:
        raise QueryError("matchesInsight requires a project", node=node)

    insight = query.source.source
    if insight.kind not in (
        "TrendsQuery",
        "FunnelsQuery",
        "RetentionQuery",
        "LifecycleQuery",
        "StickinessQuery",
        "PathsQuery",
        "PathsV2Query",
    ):
        raise QueryError("matchesInsight requires a product analytics datapoint", node=node)
    breakdown = (
        getattr(query.source, "funnelStepBreakdown", None)
        if isinstance(query.source, FunnelsActorsQuery)
        else getattr(query.source, "breakdown", None)
    )
    if BREAKDOWN_OTHER_STRING_LABEL in (breakdown if isinstance(breakdown, list) else [breakdown]):
        raise QueryError("The Other breakdown cannot be used as a dashboard filter", node=node)
    if (
        isinstance(query.source, InsightActorsQuery)
        and isinstance(insight, TrendsQuery)
        and isinstance(breakdown, list)
        and insight.breakdownFilter
        and not insight.breakdownFilter.breakdowns
        and insight.breakdownFilter.breakdown_type != "cohort"
    ):
        if len(breakdown) != 1:
            raise QueryError("The selected breakdown does not match the insight", node=node)
        query.source.breakdown = breakdown[0]
    series = getattr(insight, "series", None)
    if (
        (series and any(item.kind not in ("EventsNode", "ActionsNode") for item in series))
        or getattr(insight, "customAggregationTarget", False)
        or getattr(getattr(insight, "retentionFilter", None), "customAggregationTarget", False)
    ):
        raise QueryError("This insight does not identify PostHog users or groups", node=node)

    # Query runners depend on the resolver; importing here breaks that dependency cycle.
    from posthog.hogql_queries.actors_query_runner import ActorsQueryRunner
    from posthog.models import Team

    team = context.team or Team.objects.get(id=context.team_id)
    runner = ActorsQueryRunner(query=ActorsQuery(source=query.source), team=team, user=context.user)
    runner.validate()
    if context.user is not None:
        runner.validate_query_runner_access(context.user)
    source_runner = runner.source_query_runner
    if source_runner is None:
        raise QueryError("The insight selection has no source", node=node)
    source = source_runner.to_actors_query()
    actor_column = runner.source_id_column(source)
    if actor_column is None:
        raise QueryError("The insight selection has no user or group identifier", node=node)
    group_index = runner.group_type_index
    field = (
        f"$group_{group_index}"
        if group_index is not None
        else "$session_id"
        if runner.is_session_aggregation
        else "person_id"
    )
    return ast.CompareOperation(
        op=ast.CompareOperationOp.In,
        left=ast.Field(chain=[events_alias, field]),
        right=ast.SelectQuery(
            select=[ast.Field(chain=["selected_actors", *actor_column])],
            select_from=ast.JoinExpr(table=source, alias="selected_actors"),
        ),
    )
