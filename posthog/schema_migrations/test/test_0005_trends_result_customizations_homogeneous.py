import importlib

import pytest

VALUE_ENTRY = {"assignmentBy": "value", "color": "preset-1"}
POSITION_ENTRY = {"assignmentBy": "position", "color": "preset-2"}
VALUE_KEY = '{"series":0}'
POSITION_KEY = "0"


def _get_migration():
    module = importlib.import_module("posthog.schema_migrations.0005_trends_result_customizations_homogeneous")
    return module.Migration()


def _query(result_customizations, result_customization_by=None, kind="TrendsQuery"):
    filter_key = "trendsFilter" if kind == "TrendsQuery" else "stickinessFilter"
    insight_filter = {"resultCustomizations": result_customizations}
    if result_customization_by is not None:
        insight_filter["resultCustomizationBy"] = result_customization_by
    return {
        "kind": kind,
        "series": [{"kind": "EventsNode", "event": "$pageview"}],
        filter_key: insight_filter,
    }


@pytest.mark.parametrize(
    "result_customization_by,result_customizations,expected",
    [
        # by rank: only position entries survive
        ("position", {VALUE_KEY: VALUE_ENTRY, POSITION_KEY: POSITION_ENTRY}, {POSITION_KEY: POSITION_ENTRY}),
        # by name (explicit): only value entries survive
        ("value", {VALUE_KEY: VALUE_ENTRY, POSITION_KEY: POSITION_ENTRY}, {VALUE_KEY: VALUE_ENTRY}),
        # mode absent defaults to value
        (None, {VALUE_KEY: VALUE_ENTRY, POSITION_KEY: POSITION_ENTRY}, {VALUE_KEY: VALUE_ENTRY}),
        # entry without assignmentBy is treated as value
        ("value", {VALUE_KEY: {"color": "preset-1"}}, {VALUE_KEY: {"color": "preset-1"}}),
    ],
)
def test_drops_mismatched_entries(result_customization_by, result_customizations, expected):
    migration = _get_migration()
    query = _query(result_customizations, result_customization_by)
    assert migration.transform(query)["trendsFilter"]["resultCustomizations"] == expected


def test_leaves_homogeneous_dict_untouched():
    migration = _get_migration()
    query = _query({POSITION_KEY: POSITION_ENTRY}, "position")
    assert migration.transform(query) is query


def test_bumps_version_and_cleans_stickiness():
    migration = _get_migration()
    query = _query({VALUE_KEY: VALUE_ENTRY, POSITION_KEY: POSITION_ENTRY}, "position", kind="StickinessQuery")
    query["version"] = 4
    result = migration(query)
    assert result["stickinessFilter"]["resultCustomizations"] == {POSITION_KEY: POSITION_ENTRY}
    assert result["version"] == 5
