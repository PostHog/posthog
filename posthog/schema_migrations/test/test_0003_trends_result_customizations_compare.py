import importlib

import pytest

COMPARE_ON = {"compareFilter": {"compare": True}}

BASE_KEY = '{"series":0}'
CURRENT_KEY = '{"series":0,"compare_label":"current"}'
PREVIOUS_KEY = '{"series":0,"compare_label":"previous"}'

BASE_ENTRY = {"assignmentBy": "value", "color": "preset-1"}
CURRENT_ENTRY = {"assignmentBy": "value", "color": "preset-2"}
PREVIOUS_ENTRY = {"assignmentBy": "value", "color": "preset-3", "hidden": True}


def _get_migration():
    migration_module = importlib.import_module("posthog.schema_migrations.0003_trends_result_customizations_compare")
    return migration_module.Migration()


def _trends_query(result_customizations, compare=False, filter_extra=None, **query_extra):
    query = {
        "kind": "TrendsQuery",
        "series": [{"kind": "EventsNode", "event": "$pageview"}],
        "trendsFilter": {"resultCustomizations": result_customizations, **(filter_extra or {})},
        **(COMPARE_ON if compare else {}),
        **query_extra,
    }
    return query


@pytest.mark.parametrize(
    "compare,result_customizations,expected",
    [
        # compare on: the "current" entry is what the user sees, it wins over a stale base entry
        (
            True,
            {BASE_KEY: BASE_ENTRY, CURRENT_KEY: CURRENT_ENTRY, PREVIOUS_KEY: PREVIOUS_ENTRY},
            {BASE_KEY: CURRENT_ENTRY},
        ),
        # compare off: the base entry is what the user sees, stale labelled entries are dropped
        (
            False,
            {BASE_KEY: BASE_ENTRY, CURRENT_KEY: CURRENT_ENTRY, PREVIOUS_KEY: PREVIOUS_ENTRY},
            {BASE_KEY: BASE_ENTRY},
        ),
        # current-only: renamed to the base key
        (True, {CURRENT_KEY: CURRENT_ENTRY}, {BASE_KEY: CURRENT_ENTRY}),
        (False, {CURRENT_KEY: CURRENT_ENTRY}, {BASE_KEY: CURRENT_ENTRY}),
        # previous-only: dropped — adopting e.g. hidden=true would hide the current period too
        (True, {PREVIOUS_KEY: PREVIOUS_ENTRY}, {}),
        # order independence: current after base still wins when compare is on
        (
            True,
            {CURRENT_KEY: CURRENT_ENTRY, BASE_KEY: BASE_ENTRY},
            {BASE_KEY: CURRENT_ENTRY},
        ),
    ],
)
def test_value_mode_merges_compare_entries(compare, result_customizations, expected):
    migration = _get_migration()
    query = _trends_query(result_customizations, compare=compare)
    assert migration.transform(query)["trendsFilter"]["resultCustomizations"] == expected


def test_value_mode_compare_to_without_compare_is_compare_off():
    # compare_to alone never enables comparison (runners and UI gate on compare being
    # true), so the unlabelled entry is the one in effect and must win
    migration = _get_migration()
    query = _trends_query(
        {BASE_KEY: BASE_ENTRY, CURRENT_KEY: CURRENT_ENTRY},
        compareFilter={"compare_to": "-1w"},
    )
    assert migration.transform(query)["trendsFilter"]["resultCustomizations"] == {BASE_KEY: BASE_ENTRY}


def test_value_mode_preserves_breakdown_key_bytes():
    migration = _get_migration()
    labelled_key = '{"series":1,"breakdown_value":["Ö",null,1],"compare_label":"current"}'
    query = _trends_query({labelled_key: CURRENT_ENTRY}, compare=True)
    assert migration.transform(query)["trendsFilter"]["resultCustomizations"] == {
        '{"series":1,"breakdown_value":["Ö",null,1]}': CURRENT_ENTRY
    }


def test_value_mode_keeps_unparseable_keys():
    migration = _get_migration()
    result_customizations = {"not-json": BASE_ENTRY, CURRENT_KEY: CURRENT_ENTRY}
    query = _trends_query(result_customizations, compare=True)
    assert migration.transform(query)["trendsFilter"]["resultCustomizations"] == {
        "not-json": BASE_ENTRY,
        BASE_KEY: CURRENT_ENTRY,
    }


POSITION_FILTER = {"resultCustomizationBy": "position"}
POSITION_ENTRY_0 = {"assignmentBy": "position", "color": "preset-1"}
POSITION_ENTRY_2 = {"assignmentBy": "position", "color": "preset-2"}
POSITION_ENTRY_3 = {"assignmentBy": "position", "hidden": True}
TWO_SERIES = [{"kind": "EventsNode", "event": "$pageview"}, {"kind": "EventsNode", "event": "$autocapture"}]


@pytest.mark.parametrize(
    "result_customizations,expected",
    [
        # offset previous-period entries shift back by the series count where the slot is free
        ({"0": POSITION_ENTRY_0, "3": POSITION_ENTRY_3}, {"0": POSITION_ENTRY_0, "1": POSITION_ENTRY_3}),
        # existing base entries win over shifted ones
        ({"0": POSITION_ENTRY_0, "2": POSITION_ENTRY_2}, {"0": POSITION_ENTRY_0}),
        # non-numeric keys are preserved
        ({"0": POSITION_ENTRY_0, "junk": POSITION_ENTRY_2}, {"0": POSITION_ENTRY_0, "junk": POSITION_ENTRY_2}),
    ],
)
def test_position_mode_remaps_offset_entries(result_customizations, expected):
    migration = _get_migration()
    query = _trends_query(result_customizations, compare=True, filter_extra=POSITION_FILTER, series=TWO_SERIES)
    assert migration.transform(query)["trendsFilter"]["resultCustomizations"] == expected


@pytest.mark.parametrize(
    "filter_extra,expected_shifted_key",
    [
        ({"formulaNodes": [{"formula": "A"}, {"formula": "B"}]}, "1"),
        ({"formulas": ["A", "B"]}, "1"),
        ({"formula": "A+B"}, "2"),
    ],
)
def test_position_mode_uses_formula_count_over_series_count(filter_extra, expected_shifted_key):
    migration = _get_migration()
    query = _trends_query(
        {"3": POSITION_ENTRY_3},
        compare=True,
        filter_extra={**POSITION_FILTER, **filter_extra},
        series=TWO_SERIES + TWO_SERIES,
    )
    assert migration.transform(query)["trendsFilter"]["resultCustomizations"] == {
        expected_shifted_key: POSITION_ENTRY_3
    }


@pytest.mark.parametrize(
    "compare,query_extra",
    [
        (False, {}),
        (True, {"breakdownFilter": {"breakdown_type": "event", "breakdown": "$browser"}}),
        (True, {"breakdownFilter": {"breakdowns": [{"type": "event", "property": "$browser"}]}}),
    ],
)
def test_position_mode_skipped_when_compare_off_or_breakdown(compare, query_extra):
    migration = _get_migration()
    result_customizations = {"0": POSITION_ENTRY_0, "3": POSITION_ENTRY_3}
    query = _trends_query(
        result_customizations, compare=compare, filter_extra=POSITION_FILTER, series=TWO_SERIES, **query_extra
    )
    assert migration.transform(query)["trendsFilter"]["resultCustomizations"] == result_customizations


def test_stickiness_filter_is_migrated():
    migration = _get_migration()
    query = {
        "kind": "StickinessQuery",
        "series": [{"kind": "EventsNode", "event": "$pageview"}],
        "stickinessFilter": {"resultCustomizations": {CURRENT_KEY: CURRENT_ENTRY, PREVIOUS_KEY: PREVIOUS_ENTRY}},
        **COMPARE_ON,
    }
    assert migration.transform(query)["stickinessFilter"]["resultCustomizations"] == {BASE_KEY: CURRENT_ENTRY}


@pytest.mark.parametrize(
    "query",
    [
        {"kind": "NotTrendsQuery"},
        {"kind": "TrendsQuery", "trendsFilter": None},
        {"kind": "TrendsQuery", "trendsFilter": {}},
        {"kind": "TrendsQuery", "trendsFilter": {"resultCustomizations": None}},
        {"kind": "TrendsQuery", "trendsFilter": {"resultCustomizations": {}}},
        # new-shape query (base keys only) must pass through unchanged
        _trends_query({BASE_KEY: BASE_ENTRY}, compare=True),
    ],
)
def test_noop_queries_are_unchanged(query):
    migration = _get_migration()
    assert migration.transform(query) == query
