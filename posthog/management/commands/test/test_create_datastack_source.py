import pathlib

import pytest

from posthog.management.commands.create_datastack_source import Command

TEST_FILE_CONTENT = "a b c d e f"
TEST_BLOCK = """\
a
b
c

d
"""


@pytest.fixture
def command():
    return Command()


def test_split_file_by_regex(command: Command, tmp_path: pathlib.Path):
    path = tmp_path / "test.file"
    path.write_text(TEST_FILE_CONTENT)

    pre, post = command._split_file_by_regex(str(path), r"a b c")

    assert pre == "a b c"
    assert post == " d e f"


def test_entry_exists_in_contiguous_text_block(command: Command):
    assert command._entry_exists_in_contiguous_text_block("a", TEST_BLOCK)
    assert command._entry_exists_in_contiguous_text_block("b", TEST_BLOCK)
    assert command._entry_exists_in_contiguous_text_block("c", TEST_BLOCK)
    assert not command._entry_exists_in_contiguous_text_block("d", TEST_BLOCK)


def test_format_file_line(command: Command):
    expected = "    a\n"
    assert command._format_file_line("a") == expected
    assert command._format_file_line("a\n") == expected

    expected = "        a"
    assert command._format_file_line("a", indent_level=2, end="")
