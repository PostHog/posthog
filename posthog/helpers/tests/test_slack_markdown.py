from django.test import SimpleTestCase

from parameterized import parameterized

from posthog.helpers.slack_markdown import opens_with_line_anchored_markdown


class TestOpensWithLineAnchoredMarkdown(SimpleTestCase):
    @parameterized.expand(
        [
            ("heading", "## Heading\n\nBody."),
            ("deepest_heading", "###### Heading"),
            ("bullet_list", "- First\n- Second"),
            ("star_bullet_list", "* First"),
            ("ordered_list", "1. First"),
            ("ordered_list_parenthesis", "1) First"),
            ("block_quote", "> Quoted."),
            ("fenced_code", "```python\nprint()\n```"),
            ("tilde_fence", "~~~\ncode\n~~~"),
            ("table", "| Model | Effort |\n| --- | --- |"),
            ("thematic_break", "---\n\nBody."),
            ("indented_code", "    print()"),
            ("three_leading_spaces", "   ## Heading"),
        ]
    )
    def test_line_anchored_openings(self, _name: str, text: str) -> None:
        assert opens_with_line_anchored_markdown(text)

    @parameterized.expand(
        [
            ("prose", "Done. Your default task model is now Claude Opus 5."),
            # The marker of a heading or a list needs the space that separates it from the content,
            # so these open a paragraph and take a mention in front of them.
            ("bold_opening", "**Done.** Your default task model is now Claude Opus 5."),
            ("emphasis_opening", "*Done.* Your model is set."),
            ("hashtag", "#opus is the default now."),
            ("inline_code", "`opus-5` is the default now."),
            ("heading_later_in_the_answer", "Done.\n\n## What changed"),
            ("empty", ""),
        ]
    )
    def test_openings_that_take_a_prefix(self, _name: str, text: str) -> None:
        assert not opens_with_line_anchored_markdown(text)
