import re
import json
from collections import Counter
from collections.abc import Callable
from functools import cache, cached_property
from time import monotonic
from typing import TYPE_CHECKING, Any
from uuid import UUID

from django.db import transaction
from django.db.models import Q, QuerySet
from django.utils import timezone

from posthog.hogql import ast
from posthog.hogql.errors import ExposedHogQLError
from posthog.hogql.parser import parse_program, parse_select
from posthog.hogql.visitor import TraversingVisitor

from products.customer_analytics.backend.facade.enums import AccountViewVisibility
from products.customer_analytics.backend.models.account_view import AccountView
from products.notebooks.backend.facade import content as notebook_content
from products.notebooks.backend.facade.contracts import NotebookMarkdownContentInvalid

if TYPE_CHECKING:
    from posthog.hogql.database.database import Database

    from posthog.models.team import Team
    from posthog.models.user import User

ACCOUNT_VIEW_COMPONENT_LABELS = {
    "Properties": "Properties",
    "Notes": "Notes",
    "Context": "Context",
    "Automations": "Automations",
    "Tasks": "Tasks",
    "Users": "Users",
    "Relationships": "Relationships",
    "FeatureRequests": "Feature requests",
    "Usage": "Usage",
    "Spend": "Spend",
    "Opportunities": "Opportunities",
    "Conversations": "Conversations",
    "Meetings": "Meetings",
    "SessionReplays": "Session replays",
    "DotMatrix": "Dot matrix",
    "SqlQuery": "SQL query",
}
ACCOUNT_VIEW_ALLOWED_PROPS = {"config", "nodeId", "span", "title"}
ACCOUNT_VIEW_COMPONENT_TITLE_MAX_LENGTH = 400
ACCOUNT_VIEW_CONFIG_MAX_BYTES = 16_384
ACCOUNT_VIEW_MAX_COMPONENTS = 50
ACCOUNT_VIEW_COMPONENT_LIMITS = {"SqlQuery": 10}
ACCOUNT_VIEW_SQL_VALIDATION_SECONDS = 5
ACCOUNT_VIEW_SQL_MAX_FORMATTING_RULES = 20
ACCOUNT_VIEW_SQL_MAX_FORMATTING_BYTECODE = 256
DOT_MATRIX_PRESET_SOURCES = ("usage_metrics", "product_usage")
DOT_MATRIX_REQUIRED_MAPPING = frozenset({"row", "column"})
DOT_MATRIX_MAPPING_KEYS = frozenset({"row", "column", "series", "value", "user", "rowLabel"})
ACCOUNT_VIEW_IDENTITY_PROPS = {
    "accountId",
    "account_id",
    "externalId",
    "external_id",
    "projectId",
    "project_id",
    "teamId",
    "team_id",
}
ACCOUNT_VIEW_NODE_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9:_-]{0,127}$")
ACCOUNT_VIEW_NATIVE_PROPERTY_KEYS = {
    "website_domain",
    "billing_id",
    "slack_channel_id",
    "sfdc_id",
    "stripe_customer_id",
    "email_domains",
    "known_emails",
}
ACCOUNT_VIEW_MAX_PROPERTIES = 50


def is_account_sql_query_filter(
    expression: ast.Expr | None, aliases: set[str], allowed_fields: set[tuple[str | int, ...]] | None = None
) -> bool:
    if isinstance(expression, ast.And):
        return any(is_account_sql_query_filter(item, aliases, allowed_fields) for item in expression.exprs)
    if isinstance(expression, ast.Or):
        return bool(expression.exprs) and all(
            is_account_sql_query_filter(item, aliases, allowed_fields) for item in expression.exprs
        )
    if isinstance(expression, ast.CompareOperation) and expression.op == ast.CompareOperationOp.Eq:
        for field, placeholder in [(expression.left, expression.right), (expression.right, expression.left)]:
            if (
                isinstance(field, ast.Field)
                and (allowed_fields is None or tuple(field.chain) in allowed_fields)
                and not any(
                    ".".join(str(part) for part in field.chain[:length]) in aliases
                    for length in range(1, len(field.chain) + 1)
                )
                and isinstance(placeholder, ast.Placeholder)
                and placeholder.chain == ["account_external_id"]
            ):
                return True
    return False


class AccountSqlQueryAliasCollector(TraversingVisitor):
    def __init__(self) -> None:
        super().__init__()
        self.aliases: set[str] = set()

    def visit_alias(self, node: ast.Alias) -> None:
        self.aliases.add(node.alias)
        super().visit_alias(node)

    def visit_select_query(self, node: ast.SelectQuery) -> None:
        self.aliases.update(node.ctes or {})
        super().visit_select_query(node)


class AccountSqlQueryScopeValidator(TraversingVisitor):
    def __init__(self, aliases: set[str]) -> None:
        super().__init__()
        self.aliases = aliases

    def visit_select_query(self, node: ast.SelectQuery) -> None:
        if node.select_from and node.select_from.next_join:
            raise InvalidAccountViewContent(
                ["SQL account widgets do not support joins. Use a single table per SELECT."]
            )
        allowed_fields: set[tuple[str | int, ...]] | None = None
        if (
            node.select_from
            and isinstance(node.select_from.table, ast.Field)
            and ".".join(str(part) for part in node.select_from.table.chain) == "system.accounts"
        ):
            allowed_fields = {("external_id",), ("accounts", "external_id"), ("system", "accounts", "external_id")}
            if node.select_from.alias:
                allowed_fields.add((node.select_from.alias, "external_id"))
        reads_validated_subquery = node.select_from is not None and isinstance(
            node.select_from.table, ast.SelectQuery | ast.SelectSetQuery
        )
        if not node.select_from or (
            not reads_validated_subquery and not is_account_sql_query_filter(node.where, self.aliases, allowed_fields)
        ):
            if allowed_fields is not None:
                raise InvalidAccountViewContent(
                    ["SQL queries on system.accounts must filter external_id by {account_external_id}."]
                )
            raise InvalidAccountViewContent(["SQL query must filter by {account_external_id} in every SELECT's WHERE."])
        super().visit_select_query(node)

    def visit_placeholder(self, node: ast.Placeholder) -> None:
        if not isinstance(node.expr, ast.Field) or node.expr.chain != ["account_external_id"]:
            raise InvalidAccountViewContent(["SQL account widgets only support the {account_external_id} placeholder."])

    def visit_join_expr(self, node: ast.JoinExpr) -> None:
        if node.column_aliases:
            raise InvalidAccountViewContent(["SQL account widgets do not support table column aliases."])
        if not isinstance(node.table, ast.Field | ast.SelectQuery | ast.SelectSetQuery) or node.table_args:
            raise InvalidAccountViewContent(["SQL account widgets require a table name or scoped subquery in FROM."])
        super().visit_join_expr(node)


class InvalidAccountViewContent(ValueError):
    def __init__(self, errors: list[str]) -> None:
        super().__init__("; ".join(errors))
        self.errors = errors


class AccountViewVersionConflict(Exception):
    pass


class AccountViewPermissionDenied(Exception):
    pass


def get_account_identity_props(value: object) -> set[str]:
    if isinstance(value, dict):
        return ACCOUNT_VIEW_IDENTITY_PROPS.intersection(value) | set().union(
            *(get_account_identity_props(item) for item in value.values())
        )
    if isinstance(value, list):
        return set().union(*(get_account_identity_props(item) for item in value))
    return set()


def list_account_views(*, team_id: int, user_id: int) -> QuerySet[AccountView]:
    return (
        AccountView.objects.for_team(team_id)
        .filter(deleted_at__isnull=True)
        .filter(Q(created_by_id=user_id) | Q(visibility=AccountViewVisibility.TEAM))
        .order_by("name", "created_at")
    )


def get_account_view(*, team_id: int, user_id: int, view_id: UUID) -> AccountView | None:
    return list_account_views(team_id=team_id, user_id=user_id).filter(id=view_id).first()


def validate_properties_widget_config(config: dict[str, Any]) -> list[str]:
    if set(config).difference({"properties"}):
        return ["Properties config has unsupported fields."]
    references = config.get("properties", [])
    if not isinstance(references, list) or len(references) > ACCOUNT_VIEW_MAX_PROPERTIES:
        return ["Properties config must contain a list of up to 50 properties."]
    seen: set[tuple[str, str]] = set()
    for reference in references:
        if not isinstance(reference, dict):
            return ["Properties config contains an invalid property reference."]
        kind = reference.get("kind")
        if kind == "account":
            native_key = reference.get("key")
            if (
                set(reference) != {"kind", "key"}
                or not isinstance(native_key, str)
                or native_key not in ACCOUNT_VIEW_NATIVE_PROPERTY_KEYS
            ):
                return ["Properties config contains an unsupported account property."]
            key = (kind, native_key)
        elif kind in ("custom_property", "relationship"):
            definition_id = reference.get("id")
            if set(reference) != {"kind", "id"} or not isinstance(definition_id, str):
                return ["Properties config contains an invalid definition reference."]
            try:
                definition_uuid = UUID(definition_id)
                if definition_id.lower() != str(definition_uuid) or (
                    definition_uuid.version not in range(1, 9) and definition_uuid.int not in (0, (1 << 128) - 1)
                ):
                    return ["Properties config definition IDs must use the standard UUID format."]
                key = (kind, str(definition_uuid))
            except ValueError:
                return ["Properties config definition IDs must be UUIDs."]
        else:
            return ["Properties config contains an unsupported property source."]
        if key in seen:
            return ["Properties config cannot contain duplicate properties."]
        seen.add(key)
    return []


def _dot_matrix_key_list_errors(keys: object, label: str) -> list[str]:
    if (
        not isinstance(keys, list)
        or len(keys) > 64
        or any(not isinstance(key, str) or not 1 <= len(key) <= 128 for key in keys)
    ):
        return [f"Dot matrix config must contain up to 64 {label} of 1 to 128 characters."]
    if len(set(keys)) != len(keys):
        return [f"Dot matrix config cannot contain duplicate {label}."]
    return []


def _dot_matrix_source_errors(source: object) -> list[str]:
    if source is None:
        return []
    if not isinstance(source, dict):
        return ["Dot matrix source must be an object."]
    kind = source.get("kind")
    if kind in DOT_MATRIX_PRESET_SOURCES:
        return [] if set(source) == {"kind"} else ["Dot matrix source has unsupported fields."]
    if kind != "hogql":
        return ["Dot matrix source has an unsupported kind."]
    if set(source) != {"kind", "query", "mapping"}:
        return ["A HogQL source needs a query and a mapping."]
    query = source["query"]
    if not isinstance(query, str) or not query.strip():
        return ["A HogQL source query cannot be empty."]
    mapping = source["mapping"]
    if (
        not isinstance(mapping, dict)
        or not DOT_MATRIX_REQUIRED_MAPPING.issubset(mapping)
        or not DOT_MATRIX_MAPPING_KEYS.issuperset(mapping)
        or any(not isinstance(column, str) or not 1 <= len(column) <= 128 for column in mapping.values())
    ):
        return [
            "A HogQL source mapping needs row and column names and may add series, value, user, and row label names."
        ]
    return []


def validate_dot_matrix_widget_config(config: dict[str, object]) -> list[str]:
    if set(config).difference({"dataset", "mode", "selectedSeries", "weeks", "metricIds", "source"}):
        return ["Dot matrix config has unsupported fields."]
    if "source" in config and (source_errors := _dot_matrix_source_errors(config["source"])):
        return source_errors
    if config.get("dataset", "people") not in ("product_activity", "people", "ci"):
        return ["Dot matrix config has an unsupported dataset."]
    if config.get("mode", "dots") not in ("dots", "count"):
        return ["Dot matrix config has an unsupported display."]
    weeks = config.get("weeks", 8)
    if isinstance(weeks, bool) or not isinstance(weeks, int) or not 4 <= weeks <= 26:
        return ["Dot matrix config weeks must be a whole number from 4 to 26."]
    return _dot_matrix_key_list_errors(config.get("selectedSeries", []), "series keys") or _dot_matrix_key_list_errors(
        config.get("metricIds", []), "metric IDs"
    )


@cache
def get_account_sql_formatting_bytecodes() -> dict[str, str]:
    from posthog.hogql.compiler.bytecode import (
        create_bytecode,  # noqa: PLC0415 -- load the compiler only for formatting validation
    )

    templates = {
        "equals": "return value == input",
        "not_equals": "return value != input",
        "greater_than": "return value > input",
        "greater_than_equal": "return value >= input",
        "less_than": "return value < input",
        "less_than_equal": "return value <= input",
        "is_null": "return value == null",
        "is_not_null": "return value != null",
    }
    return {
        template_id: json.dumps(create_bytecode(parse_program(program)).bytecode)
        for template_id, program in templates.items()
    }


def validate_sql_query_widget_config(config: dict[str, Any]) -> list[str]:
    if not set(config) <= {"query", "visualization"}:
        return ["SQL query config must contain only a query and optional visualization settings."]
    query = config.get("query")
    if not isinstance(query, str) or not query.strip():
        return ["SQL query config needs a query."]
    try:
        select = parse_select(query)
    except ExposedHogQLError:
        return ["Enter a valid SQL query."]
    try:
        aliases = AccountSqlQueryAliasCollector()
        aliases.visit(select)
        AccountSqlQueryScopeValidator(aliases.aliases).visit(select)
    except InvalidAccountViewContent as error:
        return error.errors
    if "visualization" in config:
        from pydantic import ValidationError

        from posthog.schema import DataVisualizationNode

        visualization = config["visualization"]
        if not isinstance(visualization, dict) or not set(visualization) <= {
            "display",
            "chartSettings",
            "tableSettings",
        }:
            return ["SQL visualization settings are invalid."]
        try:
            node = DataVisualizationNode.model_validate(
                {"kind": "DataVisualizationNode", "source": {"kind": "HogQLQuery", "query": query}, **visualization}
            )
        except ValidationError:
            return ["SQL visualization settings are invalid."]
        rules = node.tableSettings.conditionalFormatting if node.tableSettings else None
        if rules:
            if len(rules) > ACCOUNT_VIEW_SQL_MAX_FORMATTING_RULES:
                return ["SQL tables support up to 20 conditional formatting rules. Remove extra rules."]
            if any(
                not 3 <= len(rule.bytecode) <= ACCOUNT_VIEW_SQL_MAX_FORMATTING_BYTECODE
                or rule.bytecode[:2] != ["_H", 1]
                or json.dumps(rule.bytecode) != get_account_sql_formatting_bytecodes().get(rule.templateId)
                for rule in rules
            ):
                return ["SQL conditional formatting bytecode is invalid. Recreate the formatting rule."]
    return []


ACCOUNT_VIEW_CONFIG_VALIDATORS: dict[str, Callable[[dict[str, Any]], list[str]]] = {
    "Properties": validate_properties_widget_config,
    "DotMatrix": validate_dot_matrix_widget_config,
    "SqlQuery": validate_sql_query_widget_config,
}


class AccountViewQueryAccess:
    def __init__(self, team: "Team", user: "User", can_query: bool) -> None:
        self.team = team
        self.user = user
        self.can_query = can_query
        self.deadline = monotonic() + ACCOUNT_VIEW_SQL_VALIDATION_SECONDS
        self.authorized_queries: set[str] = set()

    @cached_property
    def database(self) -> "Database":
        from posthog.hogql.database.database import Database  # noqa: PLC0415 -- load the catalog only for SQL writes

        database = Database.create_for(team=self.team, user=self.user, trigger="metadata")
        self.check_deadline()
        return database

    def check_deadline(self) -> None:
        if monotonic() >= self.deadline:
            raise InvalidAccountViewContent(["SQL validation took too long. Try fewer or simpler SQL widgets."])

    def authorize_query(self, query: str) -> None:
        if not self.can_query:
            raise AccountViewPermissionDenied("Saving SQL widgets requires the query:read API scope.")
        if query in self.authorized_queries:
            return
        self.check_deadline()

        from posthog.schema import HogLanguage, HogQLMetadata  # noqa: PLC0415 -- load query schemas only for SQL writes

        from posthog.hogql.metadata import (
            get_hogql_metadata,  # noqa: PLC0415 -- load the query engine only for SQL writes
        )

        metadata = get_hogql_metadata(
            HogQLMetadata(
                language=HogLanguage.HOG_QL,
                query=query,
                globals={"account_external_id": ""},
                freshSources=True,
            ),
            team=self.team,
            user=self.user,
            database=self.database,
        )
        self.check_deadline()
        if not metadata.isValid:
            raise AccountViewPermissionDenied("The SQL query must be valid and accessible to the person saving it.")
        self.authorized_queries.add(query)


def authorize_sql_query_widget_config(config: dict[str, Any], access: AccountViewQueryAccess) -> None:
    access.authorize_query(config["query"])


ACCOUNT_VIEW_CONFIG_AUTHORIZERS: dict[str, Callable[[dict[str, Any], AccountViewQueryAccess], None]] = {
    "SqlQuery": authorize_sql_query_widget_config,
}


def authorize_account_view_content(content: dict[str, Any], *, team: "Team", user: "User", can_query: bool) -> None:
    validated_content, _ = validate_account_view_content(content)
    access = AccountViewQueryAccess(team, user, can_query)
    for component in notebook_content.parse_markdown_component_document(validated_content):
        config = component.props.get("config")
        if config is not None and (authorize_config := ACCOUNT_VIEW_CONFIG_AUTHORIZERS.get(component.tag_name)):
            authorize_config(config, access)


def validate_account_view_content(content: dict[str, Any]) -> tuple[dict[str, Any], str]:
    try:
        components = notebook_content.parse_markdown_component_document(content)
    except NotebookMarkdownContentInvalid as error:
        raise InvalidAccountViewContent([str(error)]) from error

    if not components:
        raise InvalidAccountViewContent(["Add at least one component."])
    if len(components) > ACCOUNT_VIEW_MAX_COMPONENTS:
        raise InvalidAccountViewContent([f"Account views support up to {ACCOUNT_VIEW_MAX_COMPONENTS} components."])
    component_counts = Counter(component.tag_name for component in components)
    for tag_name, limit in ACCOUNT_VIEW_COMPONENT_LIMITS.items():
        if component_counts[tag_name] > limit:
            raise InvalidAccountViewContent(
                [f"Account views support up to {limit} {ACCOUNT_VIEW_COMPONENT_LABELS[tag_name]} components."]
            )

    errors: list[str] = []
    node_ids: set[str] = set()
    labels: list[str] = []
    for index, component in enumerate(components, start=1):
        label = ACCOUNT_VIEW_COMPONENT_LABELS.get(component.tag_name)
        if label is None:
            errors.append(f"Component {index} uses unknown type {component.tag_name}.")
            continue
        title = component.props.get("title")
        if title is None:
            labels.append(label)
        elif not isinstance(title, str) or not title.strip() or len(title) > ACCOUNT_VIEW_COMPONENT_TITLE_MAX_LENGTH:
            errors.append(f"Component {index} title must be a non-empty string up to 400 characters.")
        else:
            labels.append(title.strip())

        identity_props = ACCOUNT_VIEW_IDENTITY_PROPS.intersection(component.props)
        if identity_props:
            errors.append(f"Component {index} cannot set account identity.")

        unknown_props = set(component.props).difference(ACCOUNT_VIEW_ALLOWED_PROPS)
        if unknown_props:
            errors.append(f"Component {index} has unsupported properties: {', '.join(sorted(unknown_props))}.")

        node_id = component.props.get("nodeId")
        if not isinstance(node_id, str) or not ACCOUNT_VIEW_NODE_ID.fullmatch(node_id):
            errors.append(f"Component {index} needs a valid nodeId.")
        elif node_id in node_ids:
            errors.append(f"Component {index} duplicates nodeId {node_id}.")
        else:
            node_ids.add(node_id)

        span = component.props.get("span", 12)
        if isinstance(span, bool) or not isinstance(span, int) or not 1 <= span <= 12:
            errors.append(f"Component {index} span must be an integer from 1 to 12.")

        config = component.props.get("config")
        if config is not None:
            if not isinstance(config, dict):
                errors.append(f"Component {index} config must be an object.")
            elif identity_props := get_account_identity_props(config):
                errors.append(
                    f"Component {index} config cannot set account identity: {', '.join(sorted(identity_props))}."
                )
            elif len(json.dumps(config, separators=(",", ":")).encode()) > ACCOUNT_VIEW_CONFIG_MAX_BYTES:
                errors.append(f"Component {index} config is too large.")
            elif validate_config := ACCOUNT_VIEW_CONFIG_VALIDATORS.get(component.tag_name):
                errors.extend(f"Component {index}: {error}" for error in validate_config(config))

    if errors:
        raise InvalidAccountViewContent(errors)

    return content, "\n".join(labels)


@transaction.atomic
def create_account_view(*, team_id: int, user_id: int, name: str, content: dict[str, Any]) -> AccountView:
    validated_content, text_content = validate_account_view_content(content)
    return AccountView.objects.for_team(team_id).create(
        team_id=team_id,
        name=name,
        visibility=AccountViewVisibility.PRIVATE,
        content=validated_content,
        text_content=text_content,
        created_by_id=user_id,
        last_modified_by_id=user_id,
    )


@transaction.atomic
def update_account_view(
    *,
    team_id: int,
    user_id: int,
    view_id: UUID,
    expected_version: int,
    can_edit_team_views: bool,
    is_project_admin: bool,
    name: str | None = None,
    content: dict[str, Any] | None = None,
    visibility: str | None = None,
) -> AccountView | None:
    view = (
        AccountView.objects.for_team(team_id)
        .select_for_update()
        .filter(id=view_id, deleted_at__isnull=True)
        .filter(Q(created_by_id=user_id) | Q(visibility=AccountViewVisibility.TEAM))
        .first()
    )
    if view is None:
        return None
    if view.version != expected_version:
        raise AccountViewVersionConflict("This view changed since you opened it.")
    if view.visibility == AccountViewVisibility.PRIVATE and view.created_by_id != user_id:
        raise AccountViewPermissionDenied("Only the creator can edit this personal view.")
    if (
        view.visibility == AccountViewVisibility.TEAM
        and (name is not None or content is not None)
        and not can_edit_team_views
    ):
        raise AccountViewPermissionDenied("You need editor access to change this team view.")
    if (
        visibility is not None
        and visibility != view.visibility
        and view.created_by_id != user_id
        and not is_project_admin
    ):
        raise AccountViewPermissionDenied("Only the creator or a project admin can change visibility.")
    if name is None and content is None and (visibility is None or visibility == view.visibility):
        return view

    update_fields = ["last_modified_by", "version", "updated_at"]
    if name is not None:
        view.name = name
        update_fields.append("name")
    if content is not None:
        view.content, view.text_content = validate_account_view_content(content)
        update_fields.extend(["content", "text_content"])
    if visibility is not None and visibility != view.visibility:
        view.visibility = AccountViewVisibility(visibility)
        update_fields.append("visibility")
        if view.visibility == AccountViewVisibility.PRIVATE and view.created_by_id != user_id:
            view.created_by_id = user_id
            update_fields.append("created_by")

    view.last_modified_by_id = user_id
    view.version += 1
    view.save(update_fields=update_fields)
    return view


@transaction.atomic
def delete_account_view(
    *, team_id: int, user_id: int, view_id: UUID, expected_version: int, is_project_admin: bool
) -> bool:
    view = (
        AccountView.objects.for_team(team_id)
        .select_for_update()
        .filter(id=view_id, deleted_at__isnull=True)
        .filter(Q(created_by_id=user_id) | Q(visibility=AccountViewVisibility.TEAM))
        .first()
    )
    if view is None:
        return False
    if view.version != expected_version:
        raise AccountViewVersionConflict("This view changed since you opened it.")
    if view.created_by_id != user_id and not is_project_admin:
        raise AccountViewPermissionDenied("Only the creator or a project admin can delete this view.")

    view.deleted_at = timezone.now()
    view.last_modified_by_id = user_id
    view.version += 1
    view.save(update_fields=["deleted_at", "last_modified_by", "version", "updated_at"])
    return True
