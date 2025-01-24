from posthog.hogql import ast
from posthog.hogql.modifiers import create_default_modifiers_for_team
from posthog.hogql.parser import parse_expr
from posthog.hogql.query import execute_hogql_query
from posthog.hogql.timings import HogQLTimings
from posthog.models.team.team import Team
from posthog.schema import HogQLQueryResponse


def get_query_ast() -> ast.SelectQuery:
    exposure_query = ast.SelectQuery(
        select=[
            ast.Field(chain=["timestamp"]),
            ast.Field(chain=["distinct_id"]),
            parse_expr("replaceAll(JSONExtractRaw(properties, '$feature_flag_response'), '\"', '') AS variant"),
        ],
        select_from=ast.JoinExpr(table=ast.Field(chain=["events"])),
        where=parse_expr(
            "event = '$feature_flag_called' and replaceAll(JSONExtractRaw(properties, '$feature_flag'), '\"', '') = 'test-win-probs-2' "
        ),
    )

    events_after_exposure_query = ast.SelectQuery(
        select=[
            ast.Field(chain=["events", "timestamp"]),
            ast.Field(chain=["events", "distinct_id"]),
            ast.Field(chain=["exposure", "variant"]),
            ast.Field(chain=["events", "event"]),
        ],
        select_from=ast.JoinExpr(
            table=ast.Field(chain=["events"]),
            next_join=ast.JoinExpr(
                table=exposure_query,
                join_type="INNER JOIN",
                alias="exposure",
                constraint=ast.JoinConstraint(
                    expr=ast.CompareOperation(
                        left=ast.Field(chain=["events", "distinct_id"]),
                        right=ast.Field(chain=["exposure", "distinct_id"]),
                        op=ast.CompareOperationOp.Eq,
                    ),
                    constraint_type="ON",
                ),
            ),
        ),
        where=ast.CompareOperation(
            left=ast.Field(chain=["events", "timestamp"]),
            right=ast.Field(chain=["exposure", "timestamp"]),
            op=ast.CompareOperationOp.GtEq,
        ),
        # where=parse_expr("event in ('signup started', 'signup completed')"),
    )

    metrics_aggregated_per_user_query = ast.SelectQuery(
        select=[
            ast.Field(chain=["eae", "variant"]),
            ast.Field(chain=["eae", "event"]),
            ast.Field(chain=["eae", "distinct_id"]),
            parse_expr("count(*) as count"),
        ],
        select_from=ast.JoinExpr(table=events_after_exposure_query, alias="eae"),
        group_by=[
            ast.Field(chain=["eae", "variant"]),
            ast.Field(chain=["eae", "event"]),
            ast.Field(chain=["eae", "distinct_id"]),
        ],
    )

    final_query = ast.SelectQuery(
        select=[
            ast.Field(chain=["maq", "variant"]),
            ast.Field(chain=["maq", "event"]),
            parse_expr("count(maq.distinct_id) as num_users"),
            parse_expr("sum(maq.count) as total_sum"),
        ],
        select_from=ast.JoinExpr(table=metrics_aggregated_per_user_query, alias="maq"),
        group_by=[ast.Field(chain=["maq", "variant"]), ast.Field(chain=["maq", "event"])],
    )

    # return aggregated_exposures_query
    # return events_after_exposure_query
    return final_query


def run_query() -> HogQLQueryResponse:
    query = get_query_ast()

    response = execute_hogql_query(
        query=query,
        team=Team.objects.get(id=1),
        timings=HogQLTimings(),
        modifiers=create_default_modifiers_for_team(Team.objects.get(id=1)),
    )

    return response
