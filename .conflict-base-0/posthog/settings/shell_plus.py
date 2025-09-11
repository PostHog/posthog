from posthog.settings.utils import get_from_env, str_to_bool

# shell_plus settings
# https://django-extensions.readthedocs.io/en/latest/shell_plus.html

SHELL_PLUS_PRINT_SQL = get_from_env("PRINT_SQL", False, type_cast=str_to_bool)
SHELL_PLUS_POST_IMPORTS = [
    (
        "datetime",
        (
            "datetime",
            "timedelta",
        ),
    ),
    ("django.utils.timezone", ("now",)),
    ("infi.clickhouse_orm.utils", ("import_submodules",)),
    ("posthog.models.filters", ("Filter",)),
    ("posthog.models.property", ("Property",)),
    ("posthog.clickhouse.client", ("sync_execute",)),
    ("posthog.hogql", ("ast")),
    ("posthog.hogql.parser", ("parse_select", "parse_expr")),
    ("posthog.hogql.query", ("execute_hogql_query")),
]
