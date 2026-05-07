from django.test import SimpleTestCase

from parameterized import parameterized

from products.conversations.backend.teams_formatting import (
    rich_content_to_teams_html,
    teams_html_to_content_and_rich_content,
)


class TestTeamsHtmlToContentAndRichContent(SimpleTestCase):
    def test_empty_string_returns_empty(self):
        text, rich = teams_html_to_content_and_rich_content("")
        assert text == ""
        assert rich is None

    def test_none_returns_empty(self):
        text, rich = teams_html_to_content_and_rich_content("")
        assert text == ""
        assert rich is None

    def test_whitespace_only_returns_empty(self):
        text, rich = teams_html_to_content_and_rich_content("   ")
        assert text == ""
        assert rich is None

    def test_plain_text_preserved(self):
        text, rich = teams_html_to_content_and_rich_content("Hello world")
        assert text == "Hello world"
        assert rich is not None
        assert rich["type"] == "doc"
        assert len(rich["content"]) == 1
        assert rich["content"][0]["content"][0]["text"] == "Hello world"

    def test_at_mention_stripped(self):
        html = '<at id="28:bot-id">SupportHog</at> help me with this'
        text, rich = teams_html_to_content_and_rich_content(html)
        assert "SupportHog" not in text
        assert "help me with this" in text

    def test_multiple_at_mentions_stripped(self):
        html = "<at>Bot</at> please help <at>AnotherBot</at>"
        text, _ = teams_html_to_content_and_rich_content(html)
        assert "Bot" not in text
        assert "AnotherBot" not in text
        assert "please help" in text

    def test_br_tags_create_paragraphs(self):
        html = "Line one<br>Line two<br/>Line three"
        text, rich = teams_html_to_content_and_rich_content(html)
        assert "Line one" in text
        assert "Line two" in text
        assert "Line three" in text
        assert rich is not None
        assert len(rich["content"]) == 3

    def test_p_tags_create_paragraphs(self):
        html = "<p>First paragraph</p><p>Second paragraph</p>"
        text, rich = teams_html_to_content_and_rich_content(html)
        assert rich is not None
        assert len(rich["content"]) == 2
        assert rich["content"][0]["content"][0]["text"] == "First paragraph"
        assert rich["content"][1]["content"][0]["text"] == "Second paragraph"

    def test_html_entities_unescaped(self):
        html = "Tom &amp; Jerry &lt;3"
        text, _ = teams_html_to_content_and_rich_content(html)
        assert "Tom & Jerry <3" in text

    def test_formatting_tags_stripped(self):
        html = "<b>bold</b> and <i>italic</i> and <a href='x'>link</a>"
        text, _ = teams_html_to_content_and_rich_content(html)
        assert text == "bold and italic and link"

    def test_div_tags_create_paragraphs(self):
        html = "<div>Block one</div><div>Block two</div>"
        text, rich = teams_html_to_content_and_rich_content(html)
        assert rich is not None
        assert len(rich["content"]) == 2

    def test_rich_content_doc_structure(self):
        text, rich = teams_html_to_content_and_rich_content("Hello")
        assert rich == {
            "type": "doc",
            "content": [
                {"type": "paragraph", "content": [{"type": "text", "text": "Hello"}]},
            ],
        }

    @parameterized.expand(
        [
            ("only_at_mention", "<at>Bot</at>", ""),
            ("only_whitespace_after_strip", "<at>Bot</at>   ", ""),
        ]
    )
    def test_mention_only_messages_return_empty(self, _name, html, expected_text):
        text, rich = teams_html_to_content_and_rich_content(html)
        assert text == expected_text
        assert rich is None


class TestRichContentToTeamsHtml(SimpleTestCase):
    def test_none_rich_content_returns_escaped_fallback(self):
        result = rich_content_to_teams_html(None, "plain <text>")
        assert result == "plain &lt;text&gt;"

    def test_empty_dict_returns_escaped_fallback(self):
        result = rich_content_to_teams_html({}, "fallback")
        assert result == "fallback"

    def test_empty_content_returns_escaped_fallback(self):
        result = rich_content_to_teams_html({"type": "doc", "content": []}, "fallback")
        assert result == "fallback"

    def test_paragraph_rendered(self):
        rich = {"type": "doc", "content": [{"type": "paragraph", "content": [{"type": "text", "text": "Hello"}]}]}
        assert rich_content_to_teams_html(rich) == "<p>Hello</p>"

    def test_bold_mark(self):
        rich = {
            "type": "doc",
            "content": [
                {
                    "type": "paragraph",
                    "content": [{"type": "text", "text": "bold", "marks": [{"type": "bold"}]}],
                }
            ],
        }
        assert rich_content_to_teams_html(rich) == "<p><b>bold</b></p>"

    def test_italic_mark(self):
        rich = {
            "type": "doc",
            "content": [
                {
                    "type": "paragraph",
                    "content": [{"type": "text", "text": "italic", "marks": [{"type": "italic"}]}],
                }
            ],
        }
        assert rich_content_to_teams_html(rich) == "<p><i>italic</i></p>"

    def test_link_mark(self):
        rich = {
            "type": "doc",
            "content": [
                {
                    "type": "paragraph",
                    "content": [
                        {
                            "type": "text",
                            "text": "click",
                            "marks": [{"type": "link", "attrs": {"href": "https://example.com"}}],
                        }
                    ],
                }
            ],
        }
        assert rich_content_to_teams_html(rich) == '<p><a href="https://example.com">click</a></p>'

    def test_code_mark(self):
        rich = {
            "type": "doc",
            "content": [
                {
                    "type": "paragraph",
                    "content": [{"type": "text", "text": "code", "marks": [{"type": "code"}]}],
                }
            ],
        }
        assert rich_content_to_teams_html(rich) == "<p><code>code</code></p>"

    def test_strike_mark(self):
        rich = {
            "type": "doc",
            "content": [
                {
                    "type": "paragraph",
                    "content": [{"type": "text", "text": "struck", "marks": [{"type": "strike"}]}],
                }
            ],
        }
        assert rich_content_to_teams_html(rich) == "<p><s>struck</s></p>"

    def test_bullet_list(self):
        rich = {
            "type": "doc",
            "content": [
                {
                    "type": "bulletList",
                    "content": [
                        {
                            "type": "listItem",
                            "content": [{"type": "paragraph", "content": [{"type": "text", "text": "item"}]}],
                        },
                    ],
                }
            ],
        }
        assert rich_content_to_teams_html(rich) == "<ul><li><p>item</p></li></ul>"

    def test_heading(self):
        rich = {
            "type": "doc",
            "content": [{"type": "heading", "attrs": {"level": 3}, "content": [{"type": "text", "text": "Title"}]}],
        }
        assert rich_content_to_teams_html(rich) == "<h3>Title</h3>"

    def test_code_block(self):
        rich = {
            "type": "doc",
            "content": [{"type": "codeBlock", "content": [{"type": "text", "text": "x = 1"}]}],
        }
        assert rich_content_to_teams_html(rich) == "<pre><code>x = 1</code></pre>"

    def test_horizontal_rule(self):
        rich = {"type": "doc", "content": [{"type": "horizontalRule"}]}
        assert rich_content_to_teams_html(rich) == "<hr/>"

    def test_hard_break(self):
        rich = {
            "type": "doc",
            "content": [
                {
                    "type": "paragraph",
                    "content": [
                        {"type": "text", "text": "before"},
                        {"type": "hardBreak"},
                        {"type": "text", "text": "after"},
                    ],
                }
            ],
        }
        assert rich_content_to_teams_html(rich) == "<p>before<br/>after</p>"

    def test_html_in_text_is_escaped(self):
        rich = {
            "type": "doc",
            "content": [{"type": "paragraph", "content": [{"type": "text", "text": "<script>alert(1)</script>"}]}],
        }
        result = rich_content_to_teams_html(rich)
        assert "<script>" not in result
        assert "&lt;script&gt;" in result

    def test_multiple_paragraphs(self):
        rich = {
            "type": "doc",
            "content": [
                {"type": "paragraph", "content": [{"type": "text", "text": "First"}]},
                {"type": "paragraph", "content": [{"type": "text", "text": "Second"}]},
            ],
        }
        assert rich_content_to_teams_html(rich) == "<p>First</p><p>Second</p>"

    def test_multiple_marks_combined(self):
        rich = {
            "type": "doc",
            "content": [
                {
                    "type": "paragraph",
                    "content": [{"type": "text", "text": "wow", "marks": [{"type": "bold"}, {"type": "italic"}]}],
                }
            ],
        }
        result = rich_content_to_teams_html(rich)
        assert result == "<p><i><b>wow</b></i></p>"
