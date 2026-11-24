import json
from datetime import UTC, datetime

import time_machine
from unittest.mock import patch

from django.http import HttpResponse
from django.test import RequestFactory, SimpleTestCase

from parameterized import parameterized

from posthog.cli_notices import CLI_NOTICE_HEADER, CliNotice, CliNoticeMiddleware, SemVer, hog_version, notices_for
from posthog.cli_notices_projection import _load_notices_without_django, render

NOW = datetime(2026, 6, 1, tzinfo=UTC)
RETIRING = CliNotice(
    id="hog-1-retiring",
    level="warning",
    message="hog 1 gets no more fixes after June 1, 2027. Move to hog 2.",
    url="https://posthog.com/docs/cli/migrating",
    from_version="1.0.0",
    below="2.0.0",
    until=datetime(2027, 6, 1, tzinfo=UTC),
    installs=("homebrew", "npm-global"),
    upgrade=True,
)
RETIRING_ITEM = {
    "id": "hog-1-retiring",
    "level": "warning",
    "message": "hog 1 gets no more fixes after June 1, 2027. Move to hog 2.",
    "url": "https://posthog.com/docs/cli/migrating",
    "from": "1.0.0",
    "below": "2.0.0",
    "until": "2027-06-01T00:00:00+00:00",
    "installs": ["homebrew", "npm-global"],
    "upgrade": True,
}


class TestCliNotices(SimpleTestCase):
    @parameterized.expand(
        [
            ("release", "hog/1.2.0", SemVer(major=1, minor=2, patch=0, prerelease=())),
            ("prerelease", "hog/0.1.0-alpha.5", SemVer(major=0, minor=1, patch=0, prerelease=("alpha", "5"))),
            ("run_from_source", "hog/dev", None),
            ("posthog_cli", "posthog-cli/0.20.1", None),
            ("browser", "Mozilla/5.0 hog/1.2.0", None),
            ("missing", None, None),
        ]
    )
    def test_reads_the_hog_version_from_the_user_agent(
        self, _name: str, user_agent: str | None, expected: SemVer | None
    ) -> None:
        assert hog_version(user_agent) == expected

    @parameterized.expand(
        [
            ("every_version", {}, "1.2.0", True),
            ("below_the_next_major", {"below": "2.0.0"}, "1.2.0", True),
            ("below_this_version", {"below": "1.2.0"}, "1.2.0", False),
            ("prerelease_sorts_below_its_release", {"below": "1.2.0"}, "1.2.0-alpha.1", True),
            ("numeric_prerelease_parts_sort_as_numbers", {"from": "1.0.0-alpha.9"}, "1.0.0-alpha.10", True),
            ("from_a_later_version", {"from": "1.3.0"}, "1.2.0", False),
            ("before_it_ends", {"until": datetime(2026, 6, 2, tzinfo=UTC)}, "1.2.0", True),
            ("once_it_ended", {"until": NOW}, "1.2.0", False),
        ]
    )
    def test_picks_the_notices_for_a_hog_version(self, _name: str, fields: dict, version: str, expected: bool) -> None:
        notice = CliNotice(
            id="notice",
            level="info",
            message="A notice.",
            from_version=fields.get("from"),
            below=fields.get("below"),
            until=fields.get("until"),
        )
        parsed = SemVer.parse(version)
        assert parsed is not None

        assert notices_for(parsed, [notice], NOW) == ([notice] if expected else [])

    @parameterized.expand(
        [
            ("id_with_spaces", {"id": "not an id"}),
            ("page_outside_posthog", {"url": "https://example.com/docs"}),
            ("lookalike_domain", {"url": "https://posthog.com.example.com/docs"}),
            ("plain_http", {"url": "http://posthog.com/docs"}),
            ("control_character", {"message": "Move to hog 2.\u001b[31m"}),
            ("bidirectional_override", {"message": "Move to hog\u202e 2."}),
            ("too_long", {"message": "x" * 301}),
            ("not_semver", {"below": "two"}),
            ("escape_sequence_in_link", {"url": "https://posthog.com/docs\u001b]8;;https://evil.example/\u0007"}),
            ("space_in_link", {"url": "https://evil.example @posthog.com/docs"}),
            ("workflow_command_in_message", {"message": "Done ##[error]failed"}),
            ("workflow_command_in_link", {"url": "https://posthog.com/docs##[error]failed"}),
            ("naive_until", {"until": datetime(2027, 6, 1)}),
        ]
    )
    def test_refuses_a_notice_hog_would_skip(self, _name: str, fields: dict) -> None:
        with self.assertRaises(ValueError):
            CliNotice(**{"id": "notice", "level": "info", "message": "A notice.", **fields})

    @parameterized.expand(
        [
            ("hog_it_names", "hog/1.2.0", True),
            ("hog_past_it", "hog/2.0.0", False),
            ("browser", "Mozilla/5.0", False),
        ]
    )
    def test_adds_the_header_to_responses_for_the_hogs_a_notice_names(
        self, _name: str, user_agent: str, expected: bool
    ) -> None:
        request = RequestFactory().get("/api/projects/2/insights/", headers={"User-Agent": user_agent})

        with patch("posthog.cli_notices.CLI_NOTICES", (RETIRING,)), time_machine.travel(NOW, tick=False):
            response = CliNoticeMiddleware(lambda _request: HttpResponse(status=401))(request)

        if expected:
            assert json.loads(response[CLI_NOTICE_HEADER]) == [RETIRING_ITEM]
        else:
            assert CLI_NOTICE_HEADER not in response

    def test_sends_a_message_with_characters_outside_ascii_as_an_ascii_header(self) -> None:
        notice = CliNotice(id="arrows", level="info", message="hog skills → hog api skills.")
        request = RequestFactory().get("/api/", headers={"User-Agent": "hog/1.2.0"})

        with patch("posthog.cli_notices.CLI_NOTICES", (notice,)):
            response = CliNoticeMiddleware(lambda _request: HttpResponse())(request)

        assert response[CLI_NOTICE_HEADER].isascii()
        assert json.loads(response[CLI_NOTICE_HEADER])[0]["message"] == "hog skills → hog api skills."

    def test_generates_the_file_hog_releases_copy_from_the_same_list(self) -> None:
        standalone = _load_notices_without_django()
        notice = standalone.CliNotice(**{field: getattr(RETIRING, field) for field in CliNotice.__slots__})

        with patch.object(standalone, "CLI_NOTICES", (notice,)):
            output = render()

        assert json.loads(output["hog/release/notices.generated.json"]) == {"notices": [RETIRING_ITEM]}

    def test_refuses_to_generate_a_list_that_names_an_id_twice(self) -> None:
        standalone = _load_notices_without_django()
        notice = standalone.CliNotice(id="twice", level="info", message="A notice.")

        with patch.object(standalone, "CLI_NOTICES", (notice, notice)), self.assertRaises(ValueError):
            render()
