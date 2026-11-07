from common.hogvm.python.stl import STL


def _concat(*args):
    return STL["arrayStringConcat"].fn(list(args), None, None, 5)


def test_array_string_concat_renders_null_and_booleans_like_the_other_vms():
    assert _concat([1, "a", None, True, False], ",") == "1,a,,true,false"


def test_array_string_concat_default_separator_and_non_array():
    assert _concat(["a", "b"]) == "ab"
    assert _concat("not an array", ",") == ""
