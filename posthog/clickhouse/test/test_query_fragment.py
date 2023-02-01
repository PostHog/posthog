from posthog.clickhouse.query_fragment import Param, QueryFragment, UniqueName


def test_formatting():
    assert QueryFragment("{a}", {"a": QueryFragment("some_expression")}) == QueryFragment("some_expression")
    assert QueryFragment("{a} + {a}", {"a": QueryFragment("some_expression")}) == QueryFragment(
        "some_expression + some_expression"
    )
    assert QueryFragment("%({a})s", {"key": Param(5), "a": QueryFragment("key")}) == QueryFragment(
        "%(key)s", {"key": Param(5)}
    )


def test_formatting_kwargs():
    assert QueryFragment("{a}", a=QueryFragment("some_expression")) == QueryFragment("some_expression")
    assert QueryFragment("{a} + {a}", a=QueryFragment("some_expression")) == QueryFragment(
        "some_expression + some_expression"
    )
    assert QueryFragment("%({a})s", key=Param(5), a=QueryFragment("key")) == QueryFragment("%(key)s", {"key": Param(5)})


def test_formatting_nested():
    a = QueryFragment("m", {"y": Param(2)})
    b = QueryFragment("n", {"z": Param(3)})
    assert QueryFragment("{a} + {b}", {"x": Param(1), "a": a, "b": b}) == QueryFragment(
        "m + n", {"x": Param(1), "y": Param(2), "z": Param(3)}
    )


def test_unique_param_name():
    __a = UniqueName("__a")
    __ab = UniqueName("__ab")
    assert QueryFragment("__a + __a + __ab + 3", {__a: Param(4), __ab: Param(5)}) == QueryFragment(
        "__a_0 + __a_0 + __ab_1 + 3", {"__a_0": Param(4), "__ab_1": Param(5)}
    )
