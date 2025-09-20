import importlib


def _get_migration():
    migration_module = importlib.import_module("posthog.schema_migrations.0002_stickiness_hidden_legend_indexes")
    return migration_module.Migration()


def test_non_trends_query_is_unchanged():
    migration = _get_migration()
    other_query = {"kind": "NotTrendsQuery"}
    assert migration.transform(other_query) == other_query


def test_query_without_trends_filter_is_unchanged():
    migration = _get_migration()
    no_filter_query = {"kind": "TrendsQuery", "trendsFilter": None}
    assert migration.transform(no_filter_query) == no_filter_query


def test_no_result_customizations():
    migration = _get_migration()
    no_result_customizations_query = {
        "kind": "TrendsQuery",
        "trendsFilter": {"hiddenLegendIndexes": [0, 1]},
    }
    none_result_customizations_query = {
        "kind": "TrendsQuery",
        "trendsFilter": {"resultCustomizations": None, "hiddenLegendIndexes": [0, 1]},
    }
    empty_result_customizations_query = {
        "kind": "TrendsQuery",
        "trendsFilter": {"resultCustomizations": {}, "hiddenLegendIndexes": [0, 1]},
    }
    expected_result = {
        "kind": "TrendsQuery",
        "trendsFilter": {
            "resultCustomizationBy": "position",
            "resultCustomizations": {
                "0": {"assignmentBy": "position", "hidden": True},
                "1": {"assignmentBy": "position", "hidden": True},
            },
        },
    }
    assert migration.transform(no_result_customizations_query) == expected_result
    assert migration.transform(none_result_customizations_query) == expected_result
    assert migration.transform(empty_result_customizations_query) == expected_result


def test_result_customizations_by_position():
    migration = _get_migration()
    result_customization_by_position_query = {
        "kind": "TrendsQuery",
        "trendsFilter": {
            "resultCustomizations": {
                "0": {"assignmentBy": "position", "color": "preset-5"},
                "2": {"assignmentBy": "position", "color": "preset-11"},
            },
            "hiddenLegendIndexes": [0, 1],
        },
    }
    expected = {
        "kind": "TrendsQuery",
        "trendsFilter": {
            "resultCustomizationBy": "position",
            "resultCustomizations": {
                "0": {"assignmentBy": "position", "color": "preset-5", "hidden": True},
                "1": {"assignmentBy": "position", "hidden": True},
                "2": {"assignmentBy": "position", "color": "preset-11"},
            },
        },
    }
    assert migration.transform(result_customization_by_position_query) == expected


def test_result_customizations_by_value_removes_hidden_legend_indexes():
    migration = _get_migration()
    result_customization_by_value_query = {
        "kind": "TrendsQuery",
        "trendsFilter": {
            "resultCustomizations": {
                '{"series":0,"breakdown_value":["Firefox"]}': {
                    "assignmentBy": "value",
                    "color": "preset-5",
                },
                '{"series":0,"breakdown_value":["Safari"]}': {
                    "assignmentBy": "value",
                    "color": "preset-11",
                },
            },
            "hiddenLegendIndexes": [0, 1],
        },
        "breakdownFilter": {"breakdown_type": "event", "breakdown": "browser"},
    }
    expected = {
        "kind": "TrendsQuery",
        "trendsFilter": {
            "resultCustomizations": {
                '{"series":0,"breakdown_value":["Firefox"]}': {
                    "assignmentBy": "value",
                    "color": "preset-5",
                },
                '{"series":0,"breakdown_value":["Safari"]}': {
                    "assignmentBy": "value",
                    "color": "preset-11",
                },
            }
        },
        "breakdownFilter": {"breakdown_type": "event", "breakdown": "browser"},
    }
    assert migration.transform(result_customization_by_value_query) == expected


def test_result_customizations_by_value_empty():
    migration = _get_migration()
    result_customization_by_value_empty_query = {
        "kind": "TrendsQuery",
        "trendsFilter": {
            "resultCustomizations": {},
            "hiddenLegendIndexes": [0, 1],
        },
    }
    expected = {
        "kind": "TrendsQuery",
        "trendsFilter": {
            "resultCustomizationBy": "position",
            "resultCustomizations": {
                "0": {"assignmentBy": "position", "hidden": True},
                "1": {"assignmentBy": "position", "hidden": True},
            },
        },
    }
    assert migration.transform(result_customization_by_value_empty_query) == expected


def test_stickiness_query_handled_similarly():
    migration = _get_migration()
    stickiness_query = {
        "kind": "StickinessQuery",
        "stickinessFilter": {"hiddenLegendIndexes": [0, 1]},
    }
    expected_result = {
        "kind": "StickinessQuery",
        "stickinessFilter": {
            "resultCustomizationBy": "position",
            "resultCustomizations": {
                "0": {"assignmentBy": "position", "hidden": True},
                "1": {"assignmentBy": "position", "hidden": True},
            },
        },
    }
    assert migration.transform(stickiness_query) == expected_result


def test_result_customizations_by_position_and_value():
    migration = _get_migration()
    mixed_result_customizations_query = {
        "kind": "StickinessQuery",
        "stickinessFilter": {
            "resultCustomizationBy": "position",
            "resultCustomizations": {
                "0": {"assignmentBy": "position", "color": "preset-5"},
                '{"series":0,"breakdown_value":["Safari"]}': {
                    "assignmentBy": "value",
                    "color": "preset-11",
                },
                "2": {"assignmentBy": "position", "color": "preset-7"},
            },
            "hiddenLegendIndexes": [0, 2],
        },
    }
    expected = {
        "kind": "StickinessQuery",
        "stickinessFilter": {
            "resultCustomizationBy": "position",
            "resultCustomizations": {
                "0": {"assignmentBy": "position", "color": "preset-5", "hidden": True},
                '{"series":0,"breakdown_value":["Safari"]}': {
                    "assignmentBy": "value",
                    "color": "preset-11",
                },
                "2": {"assignmentBy": "position", "color": "preset-7", "hidden": True},
            },
        },
    }
    assert migration.transform(mixed_result_customizations_query) == expected


def test_result_customizations_by_value_no_breakdown_no_compare():
    migration = _get_migration()
    result_customization_by_value_no_breakdown_compare_query = {
        "kind": "TrendsQuery",
        "trendsFilter": {
            "resultCustomizations": {
                '{"series":0}': {
                    "assignmentBy": "value",
                    "color": "preset-5",
                },
                '{"series":2}': {
                    "assignmentBy": "value",
                    "color": "preset-11",
                },
            },
            "hiddenLegendIndexes": [0, 1],
        },
    }
    expected = {
        "kind": "TrendsQuery",
        "trendsFilter": {
            "resultCustomizationBy": "value",
            "resultCustomizations": {
                '{"series":0}': {
                    "assignmentBy": "value",
                    "color": "preset-5",
                    "hidden": True,
                },
                '{"series":1}': {
                    "assignmentBy": "value",
                    "hidden": True,
                },
                '{"series":2}': {
                    "assignmentBy": "value",
                    "color": "preset-11",
                },
            },
        },
    }
    assert migration.transform(result_customization_by_value_no_breakdown_compare_query) == expected


def test_result_customizations_by_value_with_breakdown():
    migration = _get_migration()
    result_customization_by_value_with_breakdown_query = {
        "kind": "TrendsQuery",
        "trendsFilter": {
            "resultCustomizations": {
                '{"series":0,"breakdown_value":["Firefox"]}': {
                    "assignmentBy": "value",
                    "color": "preset-5",
                },
            },
            "hiddenLegendIndexes": [0, 1],
        },
        "breakdownFilter": {"breakdown_type": "event", "breakdown": "browser"},
    }
    expected = {
        "kind": "TrendsQuery",
        "trendsFilter": {
            "resultCustomizations": {
                '{"series":0,"breakdown_value":["Firefox"]}': {
                    "assignmentBy": "value",
                    "color": "preset-5",
                },
            }
        },
        "breakdownFilter": {"breakdown_type": "event", "breakdown": "browser"},
    }
    assert migration.transform(result_customization_by_value_with_breakdown_query) == expected


def test_result_customizations_by_value_with_breakdowns_array():
    migration = _get_migration()
    result_customization_by_value_with_breakdowns_array_query = {
        "kind": "TrendsQuery",
        "trendsFilter": {
            "resultCustomizations": {
                '{"series":0,"breakdown_value":["Firefox"]}': {
                    "assignmentBy": "value",
                    "color": "preset-5",
                },
            },
            "hiddenLegendIndexes": [0, 1],
        },
        "breakdownFilter": {"breakdowns": [{"type": "event", "property": "browser"}]},
    }
    expected = {
        "kind": "TrendsQuery",
        "trendsFilter": {
            "resultCustomizations": {
                '{"series":0,"breakdown_value":["Firefox"]}': {
                    "assignmentBy": "value",
                    "color": "preset-5",
                },
            }
        },
        "breakdownFilter": {"breakdowns": [{"type": "event", "property": "browser"}]},
    }
    assert migration.transform(result_customization_by_value_with_breakdowns_array_query) == expected


def test_result_customizations_by_value_with_compare():
    migration = _get_migration()
    result_customization_by_value_with_compare_query = {
        "kind": "TrendsQuery",
        "trendsFilter": {
            "resultCustomizations": {
                '{"series":0,"compare_against":"previous"}': {
                    "assignmentBy": "value",
                    "color": "preset-5",
                },
            },
            "hiddenLegendIndexes": [0, 1],
        },
        "compareFilter": {"compare": True},
    }
    expected = {
        "kind": "TrendsQuery",
        "trendsFilter": {
            "resultCustomizations": {
                '{"series":0,"compare_against":"previous"}': {
                    "assignmentBy": "value",
                    "color": "preset-5",
                },
            }
        },
        "compareFilter": {"compare": True},
    }
    assert migration.transform(result_customization_by_value_with_compare_query) == expected
