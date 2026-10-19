from django.test import override_settings

from parameterized import parameterized

from products.commands.backend.channels.slack.parsing import (
    ErrorTrackingIssueUrl,
    PullRequestUrl,
    SlackCommand,
    parse_slack_command,
)

URL = "https://github.com/acme/widgets/pull/7"


@parameterized.expand(
    [
        ("options_then_url", f"review --deep {URL}", "review", "--deep"),
        ("url_with_a_path", f"stamp {URL}/files", "stamp", ""),
        ("focus_text_after_url", f"qa {URL} the signup form", "qa", "the signup form"),
        ("options_on_two_lines", f"review --deep\n--no-resolve {URL}", "review", "--deep --no-resolve"),
        ("dashed_option", f"review \u2014deep {URL}", "review", "\u2014deep"),
        ("url_first", f"{URL} review --deep", "review", "--deep"),
        ("option_after_url", f"review {URL} --deep", "review", "--deep"),
    ]
)
def test_reads_a_pull_request_command(_name: str, text: str, verb: str, argument: str) -> None:
    assert parse_slack_command(text) == SlackCommand(
        subject=PullRequestUrl(repository="acme/widgets", number=7), verb=verb, argument=argument
    )


@parameterized.expand(
    [
        ("text_before_url", f"review this {URL}"),
        ("url_alone", URL),
        ("no_url", "review --deep"),
        ("issue_url", "review https://github.com/acme/widgets/issues/7"),
        ("other_host", "review https://gitlab.com/acme/widgets/pull/7"),
        ("prose_first", f"please look at {URL}"),
        ("someone_else_mentioned_first", f"<@UALICE> qa {URL} the signup form"),
    ]
)
def test_anything_else_is_not_a_command(_name: str, text: str) -> None:
    assert parse_slack_command(text) is None


ISSUE_ID = "01890a5d-ac96-774b-b3f2-3e3c8a6d2b11"


@parameterized.expand(
    [
        ("this_instance", "https://us.posthog.com", True),
        ("us_alias_host", "https://app.posthog.com", True),
        # Project ids repeat across regions, so another region's link must not act here.
        ("other_region", "https://eu.posthog.com", False),
        ("lookalike_host", "https://us.posthog.com.example.com", False),
        ("userinfo_trick", "https://us.posthog.com@example.com", False),
    ]
)
@override_settings(SITE_URL="https://us.posthog.com")
def test_reads_an_issue_url_only_from_this_instance(_name: str, origin: str, accepted: bool) -> None:
    command = parse_slack_command(f"resolve {origin}/project/2/error_tracking/{ISSUE_ID}")

    expected = ErrorTrackingIssueUrl(team_id=2, issue_id=ISSUE_ID) if accepted else None
    assert (command.subject if command else None) == expected


@override_settings(SITE_URL="https://us.posthog.com")
def test_reads_the_fingerprint_link_an_alert_posts() -> None:
    command = parse_slack_command("resolve https://us.posthog.com/project/2/error-tracking/fingerprint/abc%2Fdef")

    assert command is not None and command.subject == ErrorTrackingIssueUrl(team_id=2, fingerprint="abc/def")
