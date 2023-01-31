from posthog.clickhouse.query_fragment import QueryFragment, UniqueParamName


def test_formatting_strings():
    assert QueryFragment("{a}").format(a="some_expression") == QueryFragment("some_expression")
    assert QueryFragment("{a} + {a}").format(a="some_expression") == QueryFragment("some_expression + some_expression")
    assert QueryFragment("%({a})s", {"key": 5}).format(a="key") == QueryFragment("%(key)s", {"key": 5})


def test_formatting_other_fragments():
    assert QueryFragment("{a} + {b}", {"x": 1}).format(
        a=QueryFragment("m", {"y": 2}), b=QueryFragment("n", {"z": 3})
    ) == QueryFragment("m + n", {"x": 1, "y": 2, "z": 3})


def test_unique_param_name():
    __a = UniqueParamName("__a")
    __ab = UniqueParamName("__ab")
    assert QueryFragment("__a + __a + __ab + 3", {__a: 4, __ab: 5}) == QueryFragment(
        "__a_0 + __a_0 + __ab_1 + 3", {"__a_0": 4, "__ab_1": 5}
    )
