import importlib


def test_trends_query_hidden_legend_indexes_migration():
    migration_module = importlib.import_module("posthog.schema_migrations.0002_stickiness_hidden_legend_indexes")
    migration = migration_module.Migration()

    # non-trends query is unchanged
    other_query = {"kind": "NotTrendsQuery"}
    assert migration.transform(other_query) == other_query

    # query without trendsFilter is unchanged
    no_filter_query = {"kind": "TrendsQuery", "trendsFilter": None}
    assert migration.transform(no_filter_query) == no_filter_query

    # no result customizations
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

    # result customizations by position
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
    assert migration.transform(result_customization_by_position_query) == {
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

    # result customizations by value (removes hiddenLegendIndexes, as we can't convert them without fetching breakdown values)
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
    assert migration.transform(result_customization_by_value_query) == {
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

    # result customizations by value, but result customizations are empty
    result_customization_by_value_empty_query = {
        "kind": "TrendsQuery",
        "trendsFilter": {
            "resultCustomizations": {},
            "hiddenLegendIndexes": [0, 1],
        },
    }
    assert migration.transform(result_customization_by_value_empty_query) == {
        "kind": "TrendsQuery",
        "trendsFilter": {
            "resultCustomizationBy": "position",
            "resultCustomizations": {
                "0": {"assignmentBy": "position", "hidden": True},
                "1": {"assignmentBy": "position", "hidden": True},
            },
        },
    }

    # stickiness query is handled similarly
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

    # result customizations by position, but also present for value (should leave value ones intact)
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
    assert migration.transform(mixed_result_customizations_query) == {
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

    # result customizations by value, no breakdown, no compare (should convert)
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
    assert migration.transform(result_customization_by_value_no_breakdown_compare_query) == {
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

    # result customizations by value, with breakdown (should NOT convert, just remove hiddenLegendIndexes)
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
    assert migration.transform(result_customization_by_value_with_breakdown_query) == {
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

    # result customizations by value, with breakdowns array (should NOT convert, just remove hiddenLegendIndexes)
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
    assert migration.transform(result_customization_by_value_with_breakdowns_array_query) == {
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

    # result customizations by value, with compare (should NOT convert, just remove hiddenLegendIndexes)
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
    assert migration.transform(result_customization_by_value_with_compare_query) == {
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
    migration_module = importlib.import_module("posthog.schema_migrations.0002_stickiness_hidden_legend_indexes")
    migration = migration_module.Migration()
