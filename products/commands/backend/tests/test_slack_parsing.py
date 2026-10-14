from parameterized import parameterized

from products.commands.backend.channels.slack.parsing import SlackPullRequestCommand, parse_slack_command

URL = "https://github.com/acme/widgets/pull/7"


@parameterized.expand(
    [
        ("url_then_command", f"{URL} review --deep", "review", "--deep"),
        ("url_with_a_path", f"{URL}/files stamp", "stamp", ""),
        ("focus_text", f"{URL} qa the signup form", "qa", "the signup form"),
        ("options_on_two_lines", f"{URL} review --deep\n--no-resolve", "review", "--deep --no-resolve"),
    ]
)
def test_reads_a_pull_request_command(_name: str, text: str, verb: str, argument: str) -> None:
    assert parse_slack_command(text) == SlackPullRequestCommand(
        repository="acme/widgets", pr_number=7, verb=verb, argument=argument
    )


@parameterized.expand(
    [
        ("verb_before_url", f"review {URL}"),
        ("issue_url", "https://github.com/acme/widgets/issues/7 review"),
        ("other_host", "https://gitlab.com/acme/widgets/pull/7 review"),
        ("no_verb", URL),
        ("prose_first", f"please look at {URL} review"),
        ("someone_else_mentioned_first", f"<@UALICE> {URL} qa the signup form"),
    ]
)
def test_anything_else_is_not_a_command(_name: str, text: str) -> None:
    assert parse_slack_command(text) is None
