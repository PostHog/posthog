from django.test import SimpleTestCase

from parameterized import parameterized

from products.conversations.backend.formatting import (
    extract_images_from_rich_content,
    extract_slack_user_ids,
    rich_content_to_slack_payload,
    slack_to_content_and_rich_content,
)


class TestSlackFormatting(SimpleTestCase):
    @parameterized.expand(
        [
            ("single_newline", "line1\nline2", "line1  \nline2"),
            ("double_newline", "line1\n\nline2", "line1\n\nline2"),
            ("mrkdwn_marks", "*bold*\n_italic_", "**bold**  \n*italic*"),
        ]
    )
    def test_text_fallback_normalizes_newlines(self, _name: str, slack_text: str, expected: str) -> None:
        content, rich_content = slack_to_content_and_rich_content(slack_text, None)
        assert content == expected
        assert rich_content is None

    def test_inbound_blocks_parse_nested_styles_and_links(self) -> None:
        blocks = [
            {
                "type": "rich_text",
                "elements": [
                    {
                        "type": "rich_text_section",
                        "elements": [
                            {"type": "text", "text": "Bold ", "style": {"bold": True}},
                            {
                                "type": "link",
                                "url": "https://posthog.com",
                                "text": "combo",
                                "style": {"italic": True, "underline": True},
                            },
                            {"type": "text", "text": "\nNext line"},
                        ],
                    }
                ],
            }
        ]

        content, rich_content = slack_to_content_and_rich_content("", blocks)

        assert content == "**Bold **[*combo*](https://posthog.com)  \nNext line"
        assert rich_content is not None

        first_paragraph = rich_content["content"][0]
        assert first_paragraph["type"] == "paragraph"

        link_text_node = first_paragraph["content"][1]
        assert link_text_node["text"] == "combo"
        assert {"type": "italic"} in link_text_node["marks"]
        assert {"type": "underline"} in link_text_node["marks"]
        assert {"type": "link", "attrs": {"href": "https://posthog.com"}} in link_text_node["marks"]

    def test_outbound_rich_content_emits_blocks_and_text_fallback(self) -> None:
        rich_content = {
            "type": "doc",
            "content": [
                {
                    "type": "paragraph",
                    "content": [
                        {
                            "type": "text",
                            "text": "Combo",
                            "marks": [
                                {"type": "bold"},
                                {"type": "italic"},
                                {"type": "underline"},
                                {"type": "link", "attrs": {"href": "https://posthog.com"}},
                            ],
                        }
                    ],
                }
            ],
        }

        slack_text, slack_blocks = rich_content_to_slack_payload(rich_content, "")
        assert slack_blocks is not None
        assert slack_text == "<https://posthog.com|*_Combo_*>"

        first_link = slack_blocks[0]["elements"][0]["elements"][0]
        assert first_link["type"] == "link"
        assert first_link["url"] == "https://posthog.com"
        assert first_link["style"] == {"bold": True, "italic": True, "underline": True}

    def test_rich_content_roundtrip_preserves_line_breaks_and_paragraphs(self) -> None:
        rich_content = {
            "type": "doc",
            "content": [
                {
                    "type": "paragraph",
                    "content": [
                        {"type": "text", "text": "line1"},
                        {"type": "hardBreak"},
                        {"type": "text", "text": "line2"},
                    ],
                },
                {
                    "type": "paragraph",
                    "content": [{"type": "text", "text": "line3"}],
                },
            ],
        }

        slack_text, slack_blocks = rich_content_to_slack_payload(rich_content, "")
        content, parsed_rich_content = slack_to_content_and_rich_content(slack_text, slack_blocks)

        assert content == "line1  \nline2\n\nline3"
        assert parsed_rich_content is not None
        assert len(parsed_rich_content["content"]) == 2

    def test_outbound_excludes_images_from_text_when_requested(self) -> None:
        rich_content = {
            "type": "doc",
            "content": [
                {
                    "type": "paragraph",
                    "content": [
                        {"type": "text", "text": "hello"},
                        {"type": "image", "attrs": {"src": "https://example.com/a.png", "alt": "a.png"}},
                    ],
                },
                {"type": "image", "attrs": {"src": "https://example.com/b.png", "alt": "b.png"}},
            ],
        }

        slack_text, slack_blocks = rich_content_to_slack_payload(rich_content, "", include_images=False)
        images = extract_images_from_rich_content(rich_content)

        assert slack_text == "hello"
        assert slack_blocks is not None
        assert images == [
            {"url": "https://example.com/a.png", "alt": "a.png"},
            {"url": "https://example.com/b.png", "alt": "b.png"},
        ]

    @parameterized.expand(
        [
            (
                "mrkdwn",
                "Hey <@U09CNH9SUKY> and <@U084M0KUNHF>!",
                None,
                {"U09CNH9SUKY", "U084M0KUNHF"},
            ),
            (
                "blocks_section",
                "",
                [
                    {
                        "type": "rich_text",
                        "elements": [
                            {
                                "type": "rich_text_section",
                                "elements": [
                                    {"type": "text", "text": "cc "},
                                    {"type": "user", "user_id": "U111AAA"},
                                    {"type": "text", "text": " and "},
                                    {"type": "user", "user_id": "U222BBB"},
                                ],
                            }
                        ],
                    }
                ],
                {"U111AAA", "U222BBB"},
            ),
            (
                "nested_list_block",
                "",
                [
                    {
                        "type": "rich_text",
                        "elements": [
                            {
                                "type": "rich_text_list",
                                "elements": [
                                    {
                                        "type": "rich_text_section",
                                        "elements": [
                                            {"type": "user", "user_id": "U333CCC"},
                                            {"type": "text", "text": " item one"},
                                        ],
                                    }
                                ],
                            }
                        ],
                    }
                ],
                {"U333CCC"},
            ),
            (
                "deduplicates_across_text_and_blocks",
                "<@U111AAA> hello",
                [
                    {
                        "type": "rich_text",
                        "elements": [
                            {"type": "rich_text_section", "elements": [{"type": "user", "user_id": "U111AAA"}]}
                        ],
                    }
                ],
                {"U111AAA"},
            ),
        ]
    )
    def test_extract_slack_user_ids(self, _name: str, text: str, blocks: list | None, expected: set[str]) -> None:
        assert extract_slack_user_ids(text, blocks) == expected

    @parameterized.expand(
        [
            ("mrkdwn_resolved", "Hey <@U123ABC> check this", None, {"U123ABC": "Alice"}, "Hey @Alice check this"),
            ("mrkdwn_unresolved", "Hey <@U123ABC> check this", None, None, "Hey  check this"),
        ]
    )
    def test_mrkdwn_user_mention(
        self, _name: str, text: str, blocks: list | None, user_names: dict | None, expected: str
    ) -> None:
        content, rich_content = slack_to_content_and_rich_content(text, blocks, user_names=user_names)
        assert content == expected
        assert rich_content is None

    def test_blocks_user_element_resolved_to_name(self) -> None:
        blocks = [
            {
                "type": "rich_text",
                "elements": [
                    {
                        "type": "rich_text_section",
                        "elements": [
                            {"type": "text", "text": "Hey "},
                            {"type": "user", "user_id": "U123ABC"},
                            {"type": "text", "text": " check this"},
                        ],
                    }
                ],
            }
        ]
        content, rich_content = slack_to_content_and_rich_content("", blocks, user_names={"U123ABC": "Alice"})
        assert "@Alice" in content
        assert rich_content is not None
        texts = [n.get("text", "") for n in rich_content["content"][0]["content"]]
        assert "@Alice" in texts

    def test_blocks_user_element_raw_when_unresolved(self) -> None:
        blocks = [
            {
                "type": "rich_text",
                "elements": [
                    {
                        "type": "rich_text_section",
                        "elements": [
                            {"type": "user", "user_id": "UXYZ999"},
                        ],
                    }
                ],
            }
        ]
        content, rich_content = slack_to_content_and_rich_content("", blocks)
        assert "<@UXYZ999>" in content
        assert rich_content is not None
