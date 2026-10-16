from parameterized import parameterized

from products.commands.backend.channels.slack.parsing import SlackPullRequestCommand, parse_slack_command

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
    assert parse_slack_command(text) == SlackPullRequestCommand(
        repository="acme/widgets", pr_number=7, verb=verb, argument=argument
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
