from django.test import SimpleTestCase

from parameterized import parameterized

from posthog.management.commands.apply_persons_migrations import _is_no_transaction


class TestIsNoTransaction(SimpleTestCase):
    @parameterized.expand(
        [
            ("marker_on_first_line", "-- no-transaction\nCREATE INDEX CONCURRENTLY ...", True),
            ("marker_after_blank_lines", "\n\n-- no-transaction\nCREATE INDEX ...", True),
            ("marker_with_trailing_space", "-- no-transaction   \nCREATE INDEX ...", True),
            ("no_marker", "-- add a column\nALTER TABLE ...", False),
            ("marker_not_first_statement", "ALTER TABLE ...\n-- no-transaction\n", False),
            ("empty_file", "", False),
        ]
    )
    def test_detects_marker(self, _name: str, content: str, expected: bool) -> None:
        assert _is_no_transaction(content) is expected
