import re

from posthog.event_usage import report_team_action
from posthog.models import ColumnConfiguration, Team

ACCOUNTS_COLUMN_CONFIG_CONTEXT_KEY = "customer_analytics_accounts_columns"

_DIRECT_ACCOUNT_COLUMNS = frozenset(
    {
        "id",
        "team_id",
        "external_id",
        "name",
        "properties",
        "stripe_customer_id",
        "hubspot_deal_id",
        "billing_id",
        "sfdc_id",
        "zendesk_id",
        "slack_channel_id",
        "usage_dashboard_link",
        "metabase_link",
        "slack_summary_cadence",
        "created_by_id",
        "created_at",
        "updated_at",
        "csm",
        "account_executive",
        "account_owner",
    }
)
_ALLOWED_ACCOUNT_JOIN_NAMES = frozenset(
    {"tags", "notebooks", "custom_properties", "custom_properties_history", "relationships"}
)
_ACCOUNT_JOIN_PATTERN = re.compile(r"\baccounts\.([A-Za-z_][A-Za-z0-9_]*)\.")
_TRAILING_ALIAS_PATTERN = re.compile(r"\s+AS\s+[A-Za-z_][A-Za-z0-9_]*\s*$", re.IGNORECASE)
_CUSTOM_PROPERTY_PATTERN = re.compile(
    r"^accounts\.custom_properties(?:_history)?\.values\.(`[^`]+`|[A-Za-z_][A-Za-z0-9_]*)$"
)
_RELATIONSHIP_PATTERN = re.compile(r"^accounts\.relationships\.values\.(`[^`]+`|[A-Za-z_][A-Za-z0-9_]*)$")
_TAGS_PATTERN = re.compile(r"^accounts\.tags\.(account_id|names)$")
_NOTEBOOKS_PATTERN = re.compile(r"^accounts\.notebooks\.(account_id|count)$")
_FLOAT_WRAPPER_PATTERN = re.compile(r"^toFloatOrNull\((.*)\)$", re.IGNORECASE)


def classify_account_column_expression(expression: str) -> str | None:
    external_join_names = {
        name for name in _ACCOUNT_JOIN_PATTERN.findall(expression) if name not in _ALLOWED_ACCOUNT_JOIN_NAMES
    }
    if external_join_names:
        return "external_join"

    normalized = _TRAILING_ALIAS_PATTERN.sub("", expression.strip())
    float_wrapper = _FLOAT_WRAPPER_PATTERN.fullmatch(normalized)
    if float_wrapper:
        normalized = float_wrapper.group(1).strip()

    if normalized in _DIRECT_ACCOUNT_COLUMNS:
        return None
    if any(
        pattern.fullmatch(normalized)
        for pattern in (_CUSTOM_PROPERTY_PATTERN, _RELATIONSHIP_PATTERN, _TAGS_PATTERN, _NOTEBOOKS_PATTERN)
    ):
        return None
    return "custom_sql"


def _tile_column_expressions(properties: object) -> list[str]:
    if not isinstance(properties, dict) or not isinstance(properties.get("tiles"), list):
        return []

    expressions: list[str] = []
    for tile in properties["tiles"]:
        if not isinstance(tile, dict) or not isinstance(tile.get("metric"), dict):
            continue
        expression = tile["metric"].get("columnExpression")
        if isinstance(expression, str):
            expressions.append(expression)
    return expressions


def capture_accounts_saved_view_unsupported_column_usage(team: Team) -> None:
    configurations = list(
        ColumnConfiguration.objects.filter(
            team_id=team.id,
            context_key=ACCOUNTS_COLUMN_CONFIG_CONTEXT_KEY,
        ).values_list("columns", "properties")
    )

    custom_sql_configuration_count = 0
    external_join_configuration_count = 0
    custom_sql_column_count = 0
    external_join_column_count = 0

    for columns, properties in configurations:
        classifications = [
            classify_account_column_expression(expression)
            for expression in [*(columns or []), *_tile_column_expressions(properties)]
        ]
        custom_sql_count = classifications.count("custom_sql")
        external_join_count = classifications.count("external_join")
        custom_sql_configuration_count += int(custom_sql_count > 0)
        external_join_configuration_count += int(external_join_count > 0)
        custom_sql_column_count += custom_sql_count
        external_join_column_count += external_join_count

    if custom_sql_column_count == 0 and external_join_column_count == 0:
        return

    report_team_action(
        team,
        "customer analytics accounts unsupported saved view detected",
        {
            "configuration_count": len(configurations),
            "custom_sql_configuration_count": custom_sql_configuration_count,
            "external_join_configuration_count": external_join_configuration_count,
            "custom_sql_column_count": custom_sql_column_count,
            "external_join_column_count": external_join_column_count,
        },
    )
