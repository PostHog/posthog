"""
Functions for converting Django Action and Entity models to HogQL expressions.
These functions are moved from hogql.property because they access Django models directly.
"""
from typing import Optional

from posthog.constants import AUTOCAPTURE_EVENT, TREND_FILTER_TYPE_ACTIONS
from posthog.hogql import ast
from posthog.hogql.parser import parse_expr
from posthog.hogql.property import property_to_expr
from posthog.hogql_standalone.django_adapter import create_hogql_data_bundle_from_team
from posthog.models import Action
from posthog.models.event import Selector
from posthog.models.element import Element
from posthog.models.property.util import build_selector_regex
from posthog.schema import RetentionEntity


def action_to_expr(action: Action, events_alias: Optional[str] = None) -> ast.Expr:
    """
    Convert Django Action model to HogQL expression.
    This function accesses Django models and should not be in the core hogql package.
    """
    steps = action.steps

    if len(steps) == 0:
        return ast.Constant(value=True)

    # Create data bundle for property_to_expr calls
    data_bundle = create_hogql_data_bundle_from_team(action.team)

    or_queries = []
    for step in steps:
        exprs: list[ast.Expr] = []
        if step.event:
            exprs.append(parse_expr("event = {event}", {"event": ast.Constant(value=step.event)}))

        if step.event == AUTOCAPTURE_EVENT:
            if step.selector:
                exprs.append(selector_to_expr(step.selector))
            if step.tag_name is not None:
                exprs.append(tag_name_to_expr(step.tag_name))
            if step.href is not None:
                if step.href_matching == "regex":
                    exprs.append(
                        ast.CompareOperation(
                            op=ast.CompareOperationOp.Regex,
                            left=ast.Field(chain=["elements_chain_href"]),
                            right=ast.Constant(value=step.href),
                        )
                    )
                elif step.href_matching == "contains":
                    exprs.append(
                        ast.CompareOperation(
                            op=ast.CompareOperationOp.ILike,
                            left=ast.Field(chain=["elements_chain_href"]),
                            right=ast.Constant(value=f"%{step.href}%"),
                        )
                    )
                else:
                    exprs.append(
                        ast.CompareOperation(
                            op=ast.CompareOperationOp.Eq,
                            left=ast.Field(chain=["elements_chain_href"]),
                            right=ast.Constant(value=step.href),
                        )
                    )
            if step.text is not None:
                value = step.text
                if step.text_matching == "regex":
                    exprs.append(
                        parse_expr(
                            "arrayExists(x -> x =~ {value}, elements_chain_texts)",
                            {"value": ast.Constant(value=value)},
                        )
                    )
                elif step.text_matching == "contains":
                    exprs.append(
                        parse_expr(
                            "arrayExists(x -> x ilike {value}, elements_chain_texts)",
                            {"value": ast.Constant(value=f"%{value}%")},
                        )
                    )
                else:
                    exprs.append(
                        parse_expr(
                            "arrayExists(x -> x = {value}, elements_chain_texts)",
                            {"value": ast.Constant(value=value)},
                        )
                    )

        if step.url:
            if step.url_matching == "exact":
                expr = ast.CompareOperation(
                    op=ast.CompareOperationOp.Eq,
                    left=ast.Field(
                        chain=(
                            [events_alias, "properties", "$current_url"]
                            if events_alias
                            else ["properties", "$current_url"]
                        )
                    ),
                    right=ast.Constant(value=step.url),
                )
            elif step.url_matching == "regex":
                expr = ast.CompareOperation(
                    op=ast.CompareOperationOp.Regex,
                    left=ast.Field(
                        chain=(
                            [events_alias, "properties", "$current_url"]
                            if events_alias
                            else ["properties", "$current_url"]
                        )
                    ),
                    right=ast.Constant(value=step.url),
                )
            else:
                expr = ast.CompareOperation(
                    op=ast.CompareOperationOp.Like,
                    left=ast.Field(
                        chain=(
                            [events_alias, "properties", "$current_url"]
                            if events_alias
                            else ["properties", "$current_url"]
                        )
                    ),
                    right=ast.Constant(value=f"%{step.url}%"),
                )
            exprs.append(expr)

        if step.properties:
            # Use the property_to_expr with data bundle
            from posthog.hogql_standalone.readonly_models import ReadonlyTeam
            readonly_team = ReadonlyTeam(
                id=action.team.id,
                project_id=getattr(action.team, 'project_id', None),
                timezone=action.team.timezone or "UTC",
                week_start_day=getattr(action.team, 'week_start_day', 0),
                has_group_types=bool(action.team.group_type_mapping.exists()) if hasattr(action.team, 'group_type_mapping') else False,
                person_on_events_mode=getattr(action.team, 'person_on_events_mode', False) or False,
                path_cleaning_filters=action.team.path_cleaning_filters if hasattr(action.team, 'path_cleaning_filters') else None,
            )
            exprs.append(property_to_expr(step.properties, readonly_team, data_bundle))

        if len(exprs) == 1:
            or_queries.append(exprs[0])
        elif len(exprs) > 1:
            or_queries.append(ast.And(exprs=exprs))
        else:
            or_queries.append(ast.Constant(value=True))

    if len(or_queries) == 1:
        return or_queries[0]
    else:
        return ast.Or(exprs=or_queries)


def entity_to_expr(entity: RetentionEntity, team) -> ast.Expr:
    """
    Convert RetentionEntity to HogQL expression.
    This function accesses Django models and should not be in the core hogql package.
    """
    if entity.type == TREND_FILTER_TYPE_ACTIONS and entity.id is not None:
        action = Action.objects.get(pk=entity.id)
        return action_to_expr(action)
    if entity.id is None:
        return ast.Constant(value=True)

    filters: list[ast.Expr] = [
        ast.CompareOperation(
            op=ast.CompareOperationOp.Eq,
            left=ast.Field(chain=["events", "event"]),
            right=ast.Constant(value=entity.id),
        )
    ]

    if entity.properties is not None and entity.properties != []:
        # Create data bundle for property_to_expr calls
        data_bundle = create_hogql_data_bundle_from_team(team)
        from posthog.hogql_standalone.readonly_models import ReadonlyTeam
        readonly_team = ReadonlyTeam(
            id=team.id,
            project_id=getattr(team, 'project_id', None),
            timezone=team.timezone or "UTC",
            week_start_day=getattr(team, 'week_start_day', 0),
            has_group_types=bool(team.group_type_mapping.exists()) if hasattr(team, 'group_type_mapping') else False,
            person_on_events_mode=getattr(team, 'person_on_events_mode', False) or False,
            path_cleaning_filters=team.path_cleaning_filters if hasattr(team, 'path_cleaning_filters') else None,
        )
        filters.append(property_to_expr(entity.properties, readonly_team, data_bundle))

    return ast.And(exprs=filters)


def tag_name_to_expr(tag_name: str):
    regex = rf"(^|;){tag_name}(\.|$|;|:)"
    expr = parse_expr("elements_chain =~ {regex}", {"regex": ast.Constant(value=str(regex))})
    return expr


def selector_to_expr(selector_string: str):
    selector = Selector(selector_string, escape_slashes=False)
    exprs = []
    regex = build_selector_regex(selector)
    exprs.append(parse_expr("elements_chain =~ {regex}", {"regex": ast.Constant(value=regex)}))

    useful_elements: list[ast.Expr] = []
    for part in selector.parts:
        if "tag_name" in part.data:
            if part.data["tag_name"] in Element.USEFUL_ELEMENTS:
                useful_elements.append(ast.Constant(value=part.data["tag_name"]))

        if "attr_id" in part.data:
            id_expr = parse_expr(
                "indexOf(elements_chain_ids, {value}) > 0", {"value": ast.Constant(value=part.data["attr_id"])}
            )
            if len(selector.parts) == 1 and len(part.data.keys()) == 1:
                # OPTIMIZATION: if there's only one selector part and that only filters on an ID, we don't need to also query elements_chain separately
                return id_expr
            exprs.append(id_expr)
    if len(useful_elements) > 0:
        exprs.append(
            parse_expr(
                "arrayCount(x -> x IN {value}, elements_chain_elements) > 0",
                {"value": ast.Array(exprs=useful_elements)},
            )
        )

    if len(exprs) == 1:
        return exprs[0]
    return ast.And(exprs=exprs)