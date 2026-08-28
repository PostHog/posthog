from posthog.test.base import BaseTest

from django.test import SimpleTestCase

from parameterized import parameterized

from posthog.comment.formatting import (
    _slack_emoji_name_to_char,
    _slack_unicode_to_char,
    content_to_slack_mrkdwn,
    extract_images_from_rich_content,
    extract_slack_user_ids,
    rich_content_to_html,
    rich_content_to_markdown,
    rich_content_to_slack_payload,
    slack_to_content_and_rich_content,
)
from posthog.models import Organization, User


def _paragraph(text: str) -> dict:
    return {"type": "paragraph", "content": [{"type": "text", "text": text}]}


def _list_item(*content: dict) -> dict:
    return {"type": "listItem", "content": list(content)}


class TestSlackFormatting(SimpleTestCase):
    @parameterized.expand(
        [
            ("single_newline", "line1\nline2", "line1  \nline2"),
            ("double_newline", "line1\n\nline2", "line1\n\nline2"),
            ("mrkdwn_marks", "*bold*\n_italic_", "**bold**  \n*italic*"),
            ("mrkdwn_strike", "~gone~", "~~gone~~"),
        ]
    )
    def test_text_fallback_normalizes_newlines(self, _name: str, slack_text: str, expected: str) -> None:
        content, rich_content = slack_to_content_and_rich_content(slack_text, None)
        assert content == expected
        assert rich_content is None

    @parameterized.expand(
        [
            ("channel_broadcast", "hey <!channel> look", "hey &lt;!channel&gt; look"),
            ("user_mention", "ping <@U12345>", "ping &lt;@U12345&gt;"),
            ("disguised_link", "<https://evil.com|posthog.com>", "&lt;https://evil.com|posthog.com&gt;"),
            ("ampersand", "a & b", "a &amp; b"),
            ("md_link_still_converts", "[docs](https://posthog.com)", "<https://posthog.com|docs>"),
            ("blockquote_preserved", "> quoted", "> quoted"),
            ("inline_mention", "@[Ann Lee](ann@example.com) hi", "@Ann Lee hi"),
            ("inline_mention_repeated", "@[Ann Lee](ann@example.com) @[Bo](bo@example.com)", "@Ann Lee @Bo"),
            ("inline_mention_needs_email", "@[Ann Lee](https://posthog.com)", "@<https://posthog.com|Ann Lee>"),
        ]
    )
    def test_outbound_mrkdwn_escapes_control_sequences(self, _name: str, content: str, expected: str) -> None:
        assert content_to_slack_mrkdwn(content) == expected

    def test_inline_mention_uses_slack_member_when_the_address_resolves(self) -> None:
        content = "@[Ann Lee](ann@example.com) and @[Bo](bo@example.com)"

        def resolve(email: str) -> str | None:
            return "U123" if email == "ann@example.com" else None

        assert content_to_slack_mrkdwn(content, None, resolve) == "<@U123> and @Bo"

    def test_inline_mention_falls_back_to_the_name_when_lookup_fails(self) -> None:
        def resolve(email: str) -> str | None:
            raise RuntimeError("slack is down")

        assert content_to_slack_mrkdwn("@[Ann Lee](ann@example.com) hi", None, resolve) == "@Ann Lee hi"

    @parameterized.expand(
        [
            ("alias_thumbsup", ":+1:", "\U0001f44d"),
            ("direct_lookup_fire", ":fire:", "\U0001f525"),
            ("explicit_none_shipit", ":shipit:", ":shipit:"),
            ("unknown_custom", ":acme_thing:", ":acme_thing:"),
        ]
    )
    def test_mrkdwn_emoji_shortcode_conversion(self, _name: str, mrkdwn: str, expected: str) -> None:
        content, _ = slack_to_content_and_rich_content(mrkdwn, None)
        assert content == expected

    @parameterized.expand(
        [
            (
                "with_unicode_field",
                {"type": "emoji", "name": "slightly_smiling_face", "unicode": "1f642"},
                "\U0001f642",
            ),
            ("name_only_alias", {"type": "emoji", "name": "tada"}, "\U0001f389"),
            ("name_only_direct", {"type": "emoji", "name": "rocket"}, "\U0001f680"),
            ("unknown_custom", {"type": "emoji", "name": "acme_logo"}, ":acme_logo:"),
        ]
    )
    def test_rich_text_emoji_element_conversion(self, _name: str, emoji_element: dict, expected: str) -> None:
        blocks = [{"type": "rich_text", "elements": [{"type": "rich_text_section", "elements": [emoji_element]}]}]
        _, rich_content = slack_to_content_and_rich_content("", blocks)
        assert rich_content is not None
        text_node = rich_content["content"][0]["content"][0]
        assert text_node["text"] == expected

    def test_slack_unicode_hex_compound(self) -> None:
        assert _slack_unicode_to_char("1f1fa-1f1f8") == "\U0001f1fa\U0001f1f8"

    def test_slack_unicode_hex_empty(self) -> None:
        assert _slack_unicode_to_char("") is None

    def test_slack_emoji_name_returns_none_for_unknown(self) -> None:
        assert _slack_emoji_name_to_char("totally_made_up_emoji_xyz") is None

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

        assert content == "line1  \nline2\n\n  \n\n\nline3"
        assert parsed_rich_content is not None
        # 3 paragraphs: original 2 + spacer section between them
        assert len(parsed_rich_content["content"]) == 3

    def test_inbound_preformatted_becomes_code_block(self) -> None:
        blocks = [
            {
                "type": "rich_text",
                "elements": [
                    {
                        "type": "rich_text_preformatted",
                        "elements": [{"type": "text", "text": "const x = 1\nconsole.log(x)"}],
                    }
                ],
            }
        ]

        content, rich_content = slack_to_content_and_rich_content("", blocks)

        assert rich_content is not None
        code_node = rich_content["content"][0]
        assert code_node["type"] == "codeBlock"
        assert code_node["content"] == [{"type": "text", "text": "const x = 1\nconsole.log(x)"}]
        assert content == "```\nconst x = 1\nconsole.log(x)\n```"

    def test_inbound_preformatted_preserves_non_text_elements(self) -> None:
        blocks = [
            {
                "type": "rich_text",
                "elements": [
                    {
                        "type": "rich_text_preformatted",
                        "elements": [
                            {"type": "text", "text": "see "},
                            {"type": "link", "url": "https://posthog.com"},
                            {"type": "text", "text": " or ping "},
                            {"type": "user", "user_id": "U123ABC"},
                        ],
                    }
                ],
            }
        ]

        _, rich_content = slack_to_content_and_rich_content("", blocks, user_names={"U123ABC": "Alice"})

        assert rich_content is not None
        code_node = rich_content["content"][0]
        assert code_node["type"] == "codeBlock"
        assert code_node["content"] == [{"type": "text", "text": "see https://posthog.com or ping @Alice"}]

    def test_outbound_code_block_emits_preformatted_and_nonempty_text(self) -> None:
        rich_content = {
            "type": "doc",
            "content": [
                {
                    "type": "codeBlock",
                    "attrs": {"language": "python"},
                    "content": [{"type": "text", "text": "print('hi')"}],
                }
            ],
        }

        slack_text, slack_blocks = rich_content_to_slack_payload(rich_content, "")

        assert slack_blocks is not None
        preformatted = slack_blocks[0]["elements"][0]
        assert preformatted["type"] == "rich_text_preformatted"
        assert preformatted["elements"] == [{"type": "text", "text": "print('hi')"}]
        # Guard in tasks.py only posts when text or blocks are truthy - a code-only
        # message must produce non-empty fallback text so it isn't silently dropped.
        assert slack_text.strip() != ""

    def test_outbound_empty_code_block_emits_no_preformatted_element(self) -> None:
        rich_content = {
            "type": "doc",
            "content": [
                {"type": "codeBlock", "content": []},
                {"type": "paragraph", "content": [{"type": "text", "text": "after"}]},
            ],
        }

        _, slack_blocks = rich_content_to_slack_payload(rich_content, "")

        assert slack_blocks is not None
        element_types = [el["type"] for el in slack_blocks[0]["elements"]]
        assert "rich_text_preformatted" not in element_types

    def test_code_block_roundtrip_preserves_content(self) -> None:
        rich_content = {
            "type": "doc",
            "content": [
                {
                    "type": "codeBlock",
                    "content": [{"type": "text", "text": "a = 1\nb = 2"}],
                }
            ],
        }

        slack_text, slack_blocks = rich_content_to_slack_payload(rich_content, "")
        _, parsed_rich_content = slack_to_content_and_rich_content(slack_text, slack_blocks)

        assert parsed_rich_content is not None
        code_node = parsed_rich_content["content"][0]
        assert code_node["type"] == "codeBlock"
        assert code_node["content"] == [{"type": "text", "text": "a = 1\nb = 2"}]

    @parameterized.expand(
        [
            ("single_paragraph", 1, 1),
            ("two_paragraphs", 2, 3),
            ("three_paragraphs", 3, 5),
        ]
    )
    def test_outbound_paragraph_spacer_sections(self, _name: str, para_count: int, expected_elements: int) -> None:
        rich_content = {
            "type": "doc",
            "content": [
                {"type": "paragraph", "content": [{"type": "text", "text": f"para{i + 1}"}]} for i in range(para_count)
            ],
        }

        _, slack_blocks = rich_content_to_slack_payload(rich_content, "")
        assert slack_blocks is not None

        elements = slack_blocks[0]["elements"]
        assert len(elements) == expected_elements
        for i, el in enumerate(elements):
            if i % 2 == 0:
                assert el["elements"][0]["text"] == f"para{i // 2 + 1}"
            else:
                assert el["elements"][0]["text"] == "\n"

    @parameterized.expand(
        [
            (
                "paragraphs_break_once",
                [_paragraph("one"), _paragraph("two")],
                "one\ntwo",
            ),
            (
                "authored_blank_line_stays_a_single_blank_line",
                [_paragraph("one"), {"type": "paragraph"}, _paragraph("two")],
                "one\n\ntwo",
            ),
            (
                "hard_break_drops_its_markdown_trailing_spaces",
                [
                    {
                        "type": "paragraph",
                        "content": [
                            {"type": "text", "text": "one"},
                            {"type": "hardBreak"},
                            {"type": "text", "text": "two"},
                        ],
                    }
                ],
                "one\ntwo",
            ),
            (
                "code_block_keeps_its_own_blank_lines",
                [
                    {"type": "codeBlock", "content": [{"type": "text", "text": "a = 1\n\nb = 2"}]},
                    _paragraph("after"),
                ],
                "```\na = 1\n\nb = 2\n```\nafter",
            ),
        ]
    )
    def test_outbound_text_uses_mrkdwn_line_breaks_not_markdown_ones(
        self, _name: str, content: list[dict], expected: str
    ) -> None:
        slack_text, _ = rich_content_to_slack_payload({"type": "doc", "content": content}, "")
        assert slack_text == expected

    @parameterized.expand(
        [
            # A section runs on from the one before it, so it needs a line ending plus the blank line.
            ("before_a_paragraph", _paragraph("two"), "\n\n"),
            ("before_an_image", {"type": "image", "attrs": {"src": "https://e.com/a.png", "alt": "a"}}, "\n\n"),
            # A preformatted element is its own code box, so the blank line is all it needs.
            ("before_a_code_block", {"type": "codeBlock", "content": [{"type": "text", "text": "x = 1"}]}, "\n"),
        ]
    )
    def test_outbound_blocks_keep_an_authored_blank_line(
        self, _name: str, follower: dict, expected_separator: str
    ) -> None:
        rich_content = {"type": "doc", "content": [_paragraph("one"), {"type": "paragraph"}, follower]}

        _, slack_blocks = rich_content_to_slack_payload(rich_content, "")
        assert slack_blocks is not None

        elements = slack_blocks[0]["elements"]
        assert len(elements) == 3
        assert elements[1]["elements"][0]["text"] == expected_separator

    @parameterized.expand(
        [
            ("bold_stays_bold", "**bold**", "*bold*"),
            ("italic", "*italic*", "_italic_"),
            ("bold_italic", "***both***", "*_both_*"),
            ("strike", "~~gone~~", "~gone~"),
            ("escaped_punctuation_unescaped", "e\\.g\\. query\\-time \\(v2\\)", "e.g. query-time (v2)"),
            ("escaped_syntax_not_emphasis", "2 \\* 3 \\* 4", "2 * 3 * 4"),
            ("backslash_outside_escape_set_kept", "path C:\\\\Users", "path C:\\Users"),
        ]
    )
    def test_outbound_mrkdwn_conversion(self, _name: str, markdown: str, expected: str) -> None:
        assert content_to_slack_mrkdwn(markdown) == expected

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

    def test_mention_without_an_organization_stays_generic(self) -> None:
        # No organization means no scope to resolve within, so don't touch the database at all.
        assert content_to_slack_mrkdwn("hi @member:00000000-0000-0000-0000-000000000001") == "hi @teammate"


class TestRichContentBlockNodes(SimpleTestCase):
    @parameterized.expand(
        [
            (
                "bullet_list",
                {
                    "type": "doc",
                    "content": [
                        {
                            "type": "bulletList",
                            "content": [_list_item(_paragraph("one")), _list_item(_paragraph("two"))],
                        }
                    ],
                },
                "- one\n- two",
            ),
            (
                "ordered_list_respects_start",
                {
                    "type": "doc",
                    "content": [
                        {
                            "type": "orderedList",
                            "attrs": {"start": 3},
                            "content": [_list_item(_paragraph("three")), _list_item(_paragraph("four"))],
                        }
                    ],
                },
                "3. three\n4. four",
            ),
            (
                "nested_list_indented",
                {
                    "type": "doc",
                    "content": [
                        {
                            "type": "orderedList",
                            "content": [
                                _list_item(
                                    _paragraph("parent"),
                                    {"type": "bulletList", "content": [_list_item(_paragraph("child"))]},
                                )
                            ],
                        }
                    ],
                },
                "1. parent\n   - child",
            ),
            (
                "heading_blockquote_and_rule",
                {
                    "type": "doc",
                    "content": [
                        {"type": "heading", "attrs": {"level": 2}, "content": [{"type": "text", "text": "Options"}]},
                        {"type": "blockquote", "content": [_paragraph("quoted")]},
                        {"type": "horizontalRule"},
                    ],
                },
                "## Options\n\n> quoted\n\n---",
            ),
            (
                "strike_mark",
                {
                    "type": "doc",
                    "content": [
                        {
                            "type": "paragraph",
                            "content": [{"type": "text", "text": "gone", "marks": [{"type": "strike"}]}],
                        }
                    ],
                },
                "~~gone~~",
            ),
            (
                "blockquote_wrapping_list",
                {
                    "type": "doc",
                    "content": [
                        {
                            "type": "blockquote",
                            "content": [
                                _paragraph("see options:"),
                                {
                                    "type": "bulletList",
                                    "content": [_list_item(_paragraph("one")), _list_item(_paragraph("two"))],
                                },
                            ],
                        }
                    ],
                },
                "> see options:\n> - one\n> - two",
            ),
            (
                "unknown_block_keeps_inline_content",
                {
                    "type": "doc",
                    "content": [{"type": "callout", "content": [{"type": "text", "text": "do not lose me"}]}],
                },
                "do not lose me",
            ),
        ]
    )
    def test_rich_content_to_markdown_block_nodes(self, _name: str, doc: dict, expected: str) -> None:
        assert rich_content_to_markdown(doc) == expected

    def test_slack_payload_falls_back_to_text_when_blocks_cannot_represent_doc(self) -> None:
        doc = {
            "type": "doc",
            "content": [
                _paragraph("Two options:"),
                {
                    "type": "orderedList",
                    "content": [_list_item(_paragraph("query time properties")), _list_item(_paragraph("a cohort"))],
                },
            ],
        }
        text, blocks = rich_content_to_slack_payload(doc, "fallback")
        assert blocks is None
        assert "1. query time properties" in text
        assert "2. a cohort" in text

    def test_slack_payload_maps_strike_to_slack_mrkdwn(self) -> None:
        doc = {
            "type": "doc",
            "content": [
                {
                    "type": "bulletList",
                    "content": [
                        _list_item(
                            {
                                "type": "paragraph",
                                "content": [{"type": "text", "text": "gone", "marks": [{"type": "strike"}]}],
                            }
                        )
                    ],
                }
            ],
        }
        text, blocks = rich_content_to_slack_payload(doc, "fallback")
        assert blocks is None
        assert text == "- ~gone~"

    def test_slack_text_fallback_is_not_markdown_escaped(self) -> None:
        doc = {
            "type": "doc",
            "content": [
                _paragraph("Two options (pick one):"),
                {
                    "type": "bulletList",
                    "content": [_list_item(_paragraph("Use query-time properties, e.g. person.email"))],
                },
            ],
        }
        text, blocks = rich_content_to_slack_payload(doc, "fallback")
        assert blocks is None
        assert text == "Two options (pick one):\n- Use query-time properties, e.g. person.email"

    @parameterized.expand(
        [
            ("bullet", "bullet", "bulletList", "- item one"),
            ("ordered", "ordered", "orderedList", "1. item one"),
        ]
    )
    def test_inbound_slack_list_blocks_become_list_nodes(
        self, _name: str, style: str, expected_node_type: str, expected_content_line: str
    ) -> None:
        blocks = [
            {
                "type": "rich_text",
                "elements": [
                    {
                        "type": "rich_text_list",
                        "style": style,
                        "elements": [
                            {"type": "rich_text_section", "elements": [{"type": "text", "text": "item one"}]},
                            {"type": "rich_text_section", "elements": [{"type": "text", "text": "item two"}]},
                        ],
                    }
                ],
            }
        ]
        content, rich_content = slack_to_content_and_rich_content("", blocks)
        assert rich_content is not None
        list_node = rich_content["content"][0]
        assert list_node["type"] == expected_node_type
        assert [item["type"] for item in list_node["content"]] == ["listItem", "listItem"]
        assert expected_content_line in content

    def test_rich_content_to_html_renders_hogdesk_block_nodes(self) -> None:
        doc = {
            "type": "doc",
            "content": [
                {"type": "heading", "attrs": {"level": 2}, "content": [{"type": "text", "text": "Options"}]},
                {
                    "type": "orderedList",
                    "attrs": {"start": 2},
                    "content": [
                        _list_item(
                            _paragraph("parent"),
                            {"type": "bulletList", "content": [_list_item(_paragraph("child"))]},
                        )
                    ],
                },
                {"type": "horizontalRule"},
                {
                    "type": "paragraph",
                    "content": [{"type": "text", "text": "gone", "marks": [{"type": "strike"}]}],
                },
            ],
        }
        html = rich_content_to_html(doc)
        assert "<h2>Options</h2>" in html
        assert '<ol start="2"><li>parent<ul><li>child</li></ul></li></ol>' in html
        assert "<hr>" in html
        assert "<s>gone</s>" in html

    def test_rich_content_to_html_renders_unknown_block_inline_content_as_paragraph(self) -> None:
        doc = {
            "type": "doc",
            "content": [{"type": "callout", "content": [{"type": "text", "text": "do not lose me"}]}],
        }
        html = rich_content_to_html(doc)
        assert "<p>do not lose me</p>" in html

    def test_rich_content_to_markdown_keeps_non_paragraph_blocks_in_list_items(self) -> None:
        doc = {
            "type": "doc",
            "content": [
                {
                    "type": "bulletList",
                    "content": [
                        _list_item(
                            _paragraph("intro"),
                            {"type": "heading", "attrs": {"level": 3}, "content": [{"type": "text", "text": "Step"}]},
                            {
                                "type": "codeBlock",
                                "attrs": {"language": "python"},
                                "content": [{"type": "text", "text": "print(1)"}],
                            },
                        )
                    ],
                }
            ],
        }
        md = rich_content_to_markdown(doc)
        assert "### Step" in md
        assert "```python" in md
        assert "print(1)" in md

    def test_rich_content_to_html_keeps_non_paragraph_blocks_in_list_items(self) -> None:
        doc = {
            "type": "doc",
            "content": [
                {
                    "type": "orderedList",
                    "content": [
                        _list_item(
                            _paragraph("intro"),
                            {"type": "codeBlock", "content": [{"type": "text", "text": "print(1)"}]},
                        )
                    ],
                }
            ],
        }
        html = rich_content_to_html(doc)
        assert "<li>intro<pre><code>print(1)</code></pre></li>" in html

    def test_rich_content_to_html_keeps_non_paragraph_blocks_in_blockquote(self) -> None:
        doc = {
            "type": "doc",
            "content": [
                {
                    "type": "blockquote",
                    "content": [_paragraph("see"), {"type": "bulletList", "content": [_list_item(_paragraph("one"))]}],
                }
            ],
        }
        html = rich_content_to_html(doc)
        assert "<blockquote>see<br><ul><li>one</li></ul></blockquote>" in html


class TestSlackMentionScoping(BaseTest):
    def test_mention_resolves_only_within_the_organization(self) -> None:
        # The @member marker is author-controlled and the rendered name lands in a Slack workspace,
        # so a UUID from another organization must not pull that person's name or email across.
        other_org = Organization.objects.create(name="other org")
        outsider = User.objects.create_and_join(other_org, "outsider@example.com", "password")
        self.user.first_name = "Insider"
        self.user.last_name = ""
        self.user.save()

        rendered = content_to_slack_mrkdwn(
            f"@member:{self.user.uuid} and @member:{outsider.uuid}", self.organization.id
        )

        assert rendered == "@Insider and @teammate"
        assert outsider.email not in rendered
