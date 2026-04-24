import re

import pytest

from posthog.models.ai_events.person_shims import PERSON_AI_EVENTS_SHIM_SQL, PERSON_DISTINCT_ID2_AI_EVENTS_SHIM_SQL
from posthog.models.person.sql import PERSON_DISTINCT_ID2_TABLE_BASE_SQL, PERSONS_TABLE_BASE_SQL


def _extract_column_names(create_table_sql: str) -> set[str]:
    match = re.search(r"\(\s*(.*?)\s*\)\s*ENGINE", create_table_sql, re.DOTALL)
    assert match, f"Could not parse column list from:\n{create_table_sql}"
    body = match.group(1)

    columns: set[str] = set()
    depth = 0
    current = ""
    for char in body:
        if char == "(":
            depth += 1
            current += char
        elif char == ")":
            depth -= 1
            current += char
        elif char == "," and depth == 0:
            columns.add(current.strip().split()[0].strip("`"))
            current = ""
        else:
            current += char
    if current.strip():
        columns.add(current.strip().split()[0].strip("`"))
    return columns


def _render_base_for_parsing(template: str) -> str:
    return (
        template.replace("{extra_fields}", "")
        .replace("{engine}", "MergeTree()")
        .replace("{table_name}", "probe")
        .replace("{on_cluster_clause}", "")
    )


@pytest.mark.parametrize(
    "shim_sql, base_template, shim_table_name, join_plan_columns",
    [
        (
            PERSON_DISTINCT_ID2_AI_EVENTS_SHIM_SQL,
            PERSON_DISTINCT_ID2_TABLE_BASE_SQL,
            "person_distinct_id2",
            {"team_id", "distinct_id", "person_id", "is_deleted", "version"},
        ),
        (
            PERSON_AI_EVENTS_SHIM_SQL,
            PERSONS_TABLE_BASE_SQL,
            "person",
            {"id", "team_id", "properties", "is_deleted", "version"},
        ),
    ],
)
def test_shim_shape(shim_sql, base_template, shim_table_name, join_plan_columns):
    rendered = shim_sql()

    assert f"CREATE TABLE IF NOT EXISTS {shim_table_name}" in rendered
    assert "ENGINE = Distributed" in rendered
    assert f"'{shim_table_name}'" in rendered  # data_table argument to Distributed
    assert " ON CLUSTER " not in rendered  # satellite migrations must not use ON CLUSTER

    shim_columns = _extract_column_names(rendered)
    base_columns = _extract_column_names(_render_base_for_parsing(base_template))

    assert join_plan_columns.issubset(shim_columns), (
        f"Shim is missing join-plan columns {join_plan_columns - shim_columns}"
    )
    assert shim_columns.issubset(base_columns), (
        f"Shim declares columns not in the source template: {shim_columns - base_columns}. "
        "The source may have renamed or removed a column — mirror the change on NodeRole.AI_EVENTS."
    )
