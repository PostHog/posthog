import pytest

from products.batch_exports.backend.temporal.temporary_file import remove_escaped_whitespace_recursive


@pytest.mark.parametrize(
    "value,expected",
    [
        ([1, 2, 3], [1, 2, 3]),
        ("hi\t\n\r\f\bhi", "hi hi"),
        ([["\t\n\r\f\b"]], [[""]]),
        (("\t\n\r\f\b",), ("",)),
        ({"\t\n\r\f\b"}, {""}),
        ({"key": "\t\n\r\f\b"}, {"key": ""}),
        ({"key": ["\t\n\r\f\b"]}, {"key": [""]}),
    ],
)
def test_remove_escaped_whitespace_recursive(value, expected):
    """Test we remove some whitespace values."""
    assert remove_escaped_whitespace_recursive(value) == expected
