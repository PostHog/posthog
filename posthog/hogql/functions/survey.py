from datetime import datetime

from posthog.hogql import ast
from posthog.hogql.errors import QueryError
from posthog.hogql.parser import parse_expr

from posthog.models.event.new_events_schema import use_new_events_schema


def get_survey_response(node: ast.Call, args: list[ast.Expr]) -> ast.Expr:
    """
    Process getSurveyResponse() function call and return HogQL AST.

    Args:
        node: The AST Call node for getSurveyResponse
        args: The function arguments

    Returns:
        ast.Expr representing the survey response extraction
    """
    question_index_obj = args[0]
    if not isinstance(question_index_obj, ast.Constant):
        raise QueryError("getSurveyResponse first argument must be a constant")
    if not isinstance(question_index_obj.value, int | str) or not str(question_index_obj.value).lstrip("-").isdigit():
        raise QueryError("getSurveyResponse first argument must be a valid integer")

    question_index = int(question_index_obj.value)
    second_arg = args[1] if len(args) > 1 else None
    third_arg = args[2] if len(args) > 2 else None

    question_id = str(second_arg.value) if isinstance(second_arg, ast.Constant) and second_arg.value else None
    is_multiple_choice = bool(third_arg.value) if isinstance(third_arg, ast.Constant) else False

    # Build the property keys for lookup
    id_based_key = _build_id_based_key(question_index, question_id)
    index_based_key = _build_index_based_key(question_index)

    if is_multiple_choice:
        return _build_multiple_choice_expr(id_based_key, index_based_key)

    return _build_coalesce_expr(id_based_key, index_based_key)


def _build_id_based_key(question_index: int, question_id: str | None) -> str | ast.Expr:
    """Build the ID-based property key. Returns string when static, ast.Expr when dynamic."""
    if question_id:
        return f"$survey_response_{question_id}"

    # Dynamic key: extract ID from the question at the given index in the questions array.
    return ast.Call(
        name="concat",
        args=[
            ast.Constant(value="$survey_response_"),
            ast.Call(
                name="JSONExtractString",
                args=[
                    ast.ArrayAccess(
                        array=_build_property_array_raw("$survey_questions"),
                        property=ast.Constant(value=question_index + 1),
                    ),
                    ast.Constant(value="id"),
                ],
            ),
        ],
    )


def _build_index_based_key(question_index: int) -> str:
    """Build the index-based property key string."""
    if question_index == 0:
        return "$survey_response"
    return f"$survey_response_{question_index}"


def _build_property_access(key: str | ast.Expr) -> ast.Expr:
    """Build property access expression.

    Native JSON static-key access reads the subcolumn and stringifies the value. Legacy and dynamic-key access use
    JSONExtractString to keep a consistent String return type.
    """
    if use_new_events_schema() and isinstance(key, str):
        return ast.Call(name="toString", args=[ast.Field(chain=["properties", key])])

    return ast.Call(
        name="JSONExtractString",
        args=[ast.Field(chain=["properties"]), _key_as_expr(key)],
    )


def _build_coalesce_expr(id_based_key: str | ast.Expr, index_based_key: str) -> ast.Expr:
    """Build COALESCE expression for single-choice survey response."""
    # Always check the id-based key first: modern SDKs store responses under $survey_response_<question_id>.
    # Dynamic (non-str) keys use the legacy whole-blob JSONExtract forms, which stay valid under the new
    # schema because the printer reconstructs whole-blob `properties` reads into a JSON string.
    response_keys: list[str | ast.Expr] = [id_based_key, index_based_key]

    coalesce_args: list[ast.Expr] = [
        ast.Call(
            name="nullif",
            args=[_build_property_access(response_key), ast.Constant(value="")],
        )
        for response_key in response_keys
    ]
    return ast.Call(name="coalesce", args=coalesce_args)


def _key_as_expr(key: str | ast.Expr) -> ast.Expr:
    """Convert key to ast.Expr (wrap string in Constant)."""
    return ast.Constant(value=key) if isinstance(key, str) else key


def _build_property_array_raw(key: str | ast.Expr) -> ast.Expr:
    if use_new_events_schema() and isinstance(key, str):
        json_value = ast.Call(name="toJSONString", args=[ast.Field(chain=["properties", key])])
        return ast.Call(
            name="JSONExtractArrayRaw",
            args=[ast.Call(name="ifNull", args=[json_value, ast.Constant(value="[]")])],
        )

    return ast.Call(
        name="JSONExtractArrayRaw",
        args=[ast.Field(chain=["properties"]), _key_as_expr(key)],
    )


def _build_property_presence(key: str | ast.Expr) -> ast.Expr:
    if use_new_events_schema() and isinstance(key, str):
        return ast.Call(name="isNotNull", args=[ast.Field(chain=["properties", key])])

    return ast.Call(
        name="JSONHas",
        args=[ast.Field(chain=["properties"]), _key_as_expr(key)],
    )


def _build_multiple_choice_expr(id_based_key: str | ast.Expr, index_based_key: str) -> ast.Expr:
    """Build if() expression for multiple-choice survey response.

    Note: JSONExtractArrayRaw doesn't benefit from materialization like string properties do.
    """
    index_value = _build_property_array_raw(index_based_key)
    id_value = _build_property_array_raw(id_based_key)
    return ast.Call(
        name="if",
        args=[
            ast.And(
                exprs=[
                    _build_property_presence(id_based_key),
                    ast.CompareOperation(
                        op=ast.CompareOperationOp.Gt,
                        left=ast.Call(
                            name="length",
                            args=[id_value],
                        ),
                        right=ast.Constant(value=0),
                    ),
                ]
            ),
            id_value,
            index_value,
        ],
    )


def unique_survey_submissions_filter(node: ast.Call, args: list[ast.Expr], team_id: int | None) -> ast.Expr:
    """
    Process uniqueSurveySubmissionsFilter() function call and return HogQL AST.

    Args:
        node: The AST Call node for uniqueSurveySubmissionsFilter
        args: The function arguments
        team_id: The team ID from the outer query context

    Returns:
        ast.Expr representing the unique survey submissions filter
    """
    survey_id_arg = args[0]
    if not isinstance(survey_id_arg, ast.Constant):
        raise QueryError("uniqueSurveySubmissionsFilter first argument must be a constant")

    survey_id = survey_id_arg.value
    start_timestamp_arg = args[1] if len(args) > 1 else None
    end_timestamp_arg = args[2] if len(args) > 2 else None

    # The subquery inherits the outer team filter from HogQL's normal events resolution,
    # so we only need to describe the survey/datetime predicates here.
    placeholders: dict[str, ast.Expr] = {"survey_id": ast.Constant(value=survey_id)}
    where_expr = parse_expr(
        "event = 'survey sent' AND properties.$survey_id = {survey_id}",
        placeholders=placeholders,
    )

    if start_timestamp_arg is not None:
        normalized_start_timestamp_arg = _normalize_timestamp_constant(start_timestamp_arg)
        if normalized_start_timestamp_arg is None:
            raise QueryError("uniqueSurveySubmissionsFilter second argument must be a constant")
        placeholders["start_timestamp"] = normalized_start_timestamp_arg
        where_expr = parse_expr(
            "{where} AND timestamp >= {start_timestamp}",
            placeholders={"where": where_expr, "start_timestamp": normalized_start_timestamp_arg},
        )

    if end_timestamp_arg is not None:
        normalized_end_timestamp_arg = _normalize_timestamp_constant(end_timestamp_arg)
        if normalized_end_timestamp_arg is None:
            raise QueryError("uniqueSurveySubmissionsFilter third argument must be a constant")
        placeholders["end_timestamp"] = normalized_end_timestamp_arg
        where_expr = parse_expr(
            "{where} AND timestamp <= {end_timestamp}",
            placeholders={"where": where_expr, "end_timestamp": normalized_end_timestamp_arg},
        )

    grouping_key = parse_expr(
        "if(coalesce(properties.$survey_submission_id, '') = '', toString(uuid), properties.$survey_submission_id)"
    )

    return parse_expr(
        "uuid IN (SELECT argMax(uuid, timestamp) FROM events WHERE {where} GROUP BY {grouping_key})",
        placeholders={"where": where_expr, "grouping_key": grouping_key},
        start=None,
    )


def _normalize_timestamp_constant(timestamp_arg: ast.Expr) -> ast.Constant | None:
    if not isinstance(timestamp_arg, ast.Constant):
        return None

    if isinstance(timestamp_arg.value, datetime):
        return ast.Constant(value=timestamp_arg.value.strftime("%Y-%m-%d %H:%M:%S"))

    return timestamp_arg
