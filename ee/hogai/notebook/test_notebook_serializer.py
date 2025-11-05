from typing import cast

from django.test import TestCase

from posthog.schema import (
    AssistantFunnelsQuery,
    AssistantHogQLQuery,
    AssistantTrendsEventsNode,
    AssistantTrendsQuery,
    Mark,
    ProsemirrorJSONContent,
)

from ee.hogai.notebook.notebook_serializer import (
    MarkdownTokenizer,
    NotebookContext,
    NotebookSerializer,
    cast_assistant_query,
)
from ee.hogai.utils.types.base import InsightArtifact


class TestNotebookSerializer(TestCase):
    """Test cases for the NotebookSerializer to ensure proper Markdown parsing."""

    def test_json_to_markdown_basic(self):
        """Test basic JSON to Markdown conversion."""
        serializer = NotebookSerializer()

        # Create a simple document
        doc = ProsemirrorJSONContent(
            type="doc",
            content=[
                ProsemirrorJSONContent(
                    type="heading", attrs={"level": 1}, content=[ProsemirrorJSONContent(type="text", text="Main Title")]
                ),
                ProsemirrorJSONContent(
                    type="paragraph",
                    content=[
                        ProsemirrorJSONContent(type="text", text="This is a paragraph with "),
                        ProsemirrorJSONContent(type="text", text="bold text", marks=[Mark(type="bold")]),
                        ProsemirrorJSONContent(type="text", text=" and "),
                        ProsemirrorJSONContent(type="text", text="italic text", marks=[Mark(type="italic")]),
                        ProsemirrorJSONContent(type="text", text="."),
                    ],
                ),
                ProsemirrorJSONContent(
                    type="heading", attrs={"level": 2}, content=[ProsemirrorJSONContent(type="text", text="Subheading")]
                ),
                ProsemirrorJSONContent(
                    type="paragraph", content=[ProsemirrorJSONContent(type="text", text="Another paragraph.")]
                ),
            ],
        )

        markdown = serializer.from_json_to_markdown(doc)

        expected = """# Main Title

This is a paragraph with **bold text** and *italic text*.

## Subheading

Another paragraph."""

        assert markdown == expected

    def test_json_to_markdown_lists(self):
        """Test list conversion to markdown."""
        serializer = NotebookSerializer()

        doc = ProsemirrorJSONContent(
            type="doc",
            content=[
                ProsemirrorJSONContent(
                    type="bulletList",
                    content=[
                        ProsemirrorJSONContent(
                            type="listItem",
                            content=[
                                ProsemirrorJSONContent(
                                    type="paragraph", content=[ProsemirrorJSONContent(type="text", text="First item")]
                                )
                            ],
                        ),
                        ProsemirrorJSONContent(
                            type="listItem",
                            content=[
                                ProsemirrorJSONContent(
                                    type="paragraph", content=[ProsemirrorJSONContent(type="text", text="Second item")]
                                ),
                                ProsemirrorJSONContent(
                                    type="bulletList",
                                    content=[
                                        ProsemirrorJSONContent(
                                            type="listItem",
                                            content=[
                                                ProsemirrorJSONContent(
                                                    type="paragraph",
                                                    content=[ProsemirrorJSONContent(type="text", text="Nested item")],
                                                )
                                            ],
                                        )
                                    ],
                                ),
                            ],
                        ),
                    ],
                ),
                ProsemirrorJSONContent(
                    type="orderedList",
                    attrs={"start": 5},
                    content=[
                        ProsemirrorJSONContent(
                            type="listItem",
                            content=[
                                ProsemirrorJSONContent(
                                    type="paragraph", content=[ProsemirrorJSONContent(type="text", text="Fifth item")]
                                )
                            ],
                        ),
                        ProsemirrorJSONContent(
                            type="listItem",
                            content=[
                                ProsemirrorJSONContent(
                                    type="paragraph", content=[ProsemirrorJSONContent(type="text", text="Sixth item")]
                                )
                            ],
                        ),
                    ],
                ),
            ],
        )

        markdown = serializer.from_json_to_markdown(doc)

        expected = """- First item
- Second item
  - Nested item

5. Fifth item
6. Sixth item"""

        assert markdown == expected

    def test_json_to_markdown_code_and_quotes(self):
        """Test code blocks and blockquotes conversion."""
        serializer = NotebookSerializer()

        doc = ProsemirrorJSONContent(
            type="doc",
            content=[
                ProsemirrorJSONContent(
                    type="codeBlock",
                    attrs={"language": "python"},
                    content=[ProsemirrorJSONContent(type="text", text="def hello():\n    print('Hello')")],
                ),
                ProsemirrorJSONContent(
                    type="blockquote",
                    content=[
                        ProsemirrorJSONContent(
                            type="paragraph", content=[ProsemirrorJSONContent(type="text", text="This is a quote.")]
                        ),
                        ProsemirrorJSONContent(
                            type="paragraph",
                            content=[ProsemirrorJSONContent(type="text", text="With multiple paragraphs.")],
                        ),
                    ],
                ),
            ],
        )

        markdown = serializer.from_json_to_markdown(doc)

        expected = """```python
def hello():
    print('Hello')
```

> This is a quote.
> With multiple paragraphs."""

        assert markdown == expected

    def test_json_to_markdown_tables(self):
        """Test that table nodes are not supported in markdown conversion."""
        serializer = NotebookSerializer()

        doc = ProsemirrorJSONContent(
            type="doc",
            content=[
                ProsemirrorJSONContent(
                    type="table",
                    content=[
                        ProsemirrorJSONContent(
                            type="tableRow",
                            content=[
                                ProsemirrorJSONContent(
                                    type="tableHeader", content=[ProsemirrorJSONContent(type="text", text="Header 1")]
                                ),
                                ProsemirrorJSONContent(
                                    type="tableHeader", content=[ProsemirrorJSONContent(type="text", text="Header 2")]
                                ),
                            ],
                        ),
                        ProsemirrorJSONContent(
                            type="tableRow",
                            content=[
                                ProsemirrorJSONContent(
                                    type="tableCell", content=[ProsemirrorJSONContent(type="text", text="Cell 1")]
                                ),
                                ProsemirrorJSONContent(
                                    type="tableCell", content=[ProsemirrorJSONContent(type="text", text="Cell 2")]
                                ),
                            ],
                        ),
                    ],
                )
            ],
        )

        markdown = serializer.from_json_to_markdown(doc)

        # Tables are not supported, so they should produce empty output
        assert markdown == ""

    def test_json_to_markdown_complex_marks(self):
        """Test complex inline marks conversion."""
        serializer = NotebookSerializer()

        doc = ProsemirrorJSONContent(
            type="doc",
            content=[
                ProsemirrorJSONContent(
                    type="paragraph",
                    content=[
                        ProsemirrorJSONContent(type="text", text="Text with "),
                        ProsemirrorJSONContent(type="text", text="code", marks=[Mark(type="code")]),
                        ProsemirrorJSONContent(type="text", text=", "),
                        ProsemirrorJSONContent(type="text", text="strikethrough", marks=[Mark(type="strike")]),
                        ProsemirrorJSONContent(type="text", text=", "),
                        ProsemirrorJSONContent(
                            type="text", text="link", marks=[Mark(type="link", attrs={"href": "https://example.com"})]
                        ),
                        ProsemirrorJSONContent(type="text", text=", "),
                        ProsemirrorJSONContent(type="text", text="underlined", marks=[Mark(type="underline")]),
                        ProsemirrorJSONContent(type="text", text="."),
                    ],
                )
            ],
        )

        markdown = serializer.from_json_to_markdown(doc)

        expected = "Text with `code`, ~~strikethrough~~, [link](https://example.com), <u>underlined</u>."

        assert markdown == expected

    def test_json_to_markdown_nested_marks(self):
        """Test nested marks conversion."""
        serializer = NotebookSerializer()

        doc = ProsemirrorJSONContent(
            type="doc",
            content=[
                ProsemirrorJSONContent(
                    type="paragraph",
                    content=[
                        ProsemirrorJSONContent(type="text", text="This is "),
                        ProsemirrorJSONContent(
                            type="text", text="bold and italic", marks=[Mark(type="bold"), Mark(type="italic")]
                        ),
                        ProsemirrorJSONContent(type="text", text=" text."),
                    ],
                )
            ],
        )

        markdown = serializer.from_json_to_markdown(doc)

        # Nested marks should be applied in reverse order
        expected = "This is ***bold and italic*** text."

        assert markdown == expected

    def test_json_to_markdown_images_and_hr(self):
        """Test images and horizontal rules conversion."""
        serializer = NotebookSerializer()

        doc = ProsemirrorJSONContent(
            type="doc",
            content=[
                ProsemirrorJSONContent(
                    type="image",
                    attrs={"src": "https://example.com/image.png", "alt": "Test image", "title": "Image title"},
                ),
                ProsemirrorJSONContent(type="horizontalRule"),
                ProsemirrorJSONContent(
                    type="image", attrs={"src": "https://example.com/image2.png", "alt": "Another image"}
                ),
            ],
        )

        markdown = serializer.from_json_to_markdown(doc)

        expected = """![Test image](https://example.com/image.png "Image title")

---

![Another image](https://example.com/image2.png)"""

        assert markdown == expected

    def test_markdown_to_json_basic(self):
        """Test basic markdown parsing functionality."""
        serializer = NotebookSerializer()

        # Test simple paragraph
        markdown = "This is a simple paragraph."
        result = serializer.from_markdown_to_json(markdown)
        content = result.model_dump()["content"]

        assert len(content) == 1
        assert content[0]["type"] == "paragraph"
        assert len(content[0]["content"]) == 1
        assert content[0]["content"][0]["text"] == "This is a simple paragraph."

    def test_markdown_to_json_headings(self):
        """Test markdown heading parsing."""
        serializer = NotebookSerializer()

        markdown = """# Main Title
## Subtitle
### Level 3
#### Level 4
##### Level 5
###### Level 6"""

        result = serializer.from_markdown_to_json(markdown)
        content = result.model_dump()["content"]

        assert len(content) == 6
        for i, level in enumerate([1, 2, 3, 4, 5, 6], 0):
            assert content[i]["type"] == "heading"
            assert content[i]["attrs"]["level"] == level
            assert (
                f"Level {level}" in str(content[i]["content"][0]["text"])
                or "Main Title" in str(content[i]["content"][0]["text"])
                or "Subtitle" in str(content[i]["content"][0]["text"])
            )

    def test_markdown_to_json_code_blocks(self):
        """Test markdown code block parsing."""
        serializer = NotebookSerializer()

        # Code block with language
        markdown = """```python
def hello():
    print("Hello, World!")
    return 42
```"""

        result = serializer.from_markdown_to_json(markdown)
        content = result.model_dump()["content"]

        assert len(content) == 1
        assert content[0]["type"] == "codeBlock"
        assert content[0]["attrs"]["language"] == "python"
        code_text = content[0]["content"][0]["text"]
        assert "def hello():" in code_text
        assert 'print("Hello, World!")' in code_text
        assert "return 42" in code_text

        # Code block without language
        markdown_no_lang = """```
plain code here
```"""

        result2 = serializer.from_markdown_to_json(markdown_no_lang)
        content2 = result2.model_dump()["content"]

        assert content2[0]["type"] == "codeBlock"
        assert content2[0]["attrs"] == {} or content2[0]["attrs"].get("language") is None
        assert content2[0]["content"][0]["text"] == "plain code here"

    def test_markdown_to_json_lists(self):
        """Test markdown list parsing."""
        serializer = NotebookSerializer()

        # Unordered list
        markdown_ul = """- Item 1
- Item 2
- Item 3"""

        result = serializer.from_markdown_to_json(markdown_ul)
        content = result.model_dump()["content"]

        assert len(content) == 1
        assert content[0]["type"] == "bulletList"
        assert len(content[0]["content"]) == 3

        for i, item_text in enumerate(["Item 1", "Item 2", "Item 3"], 0):
            list_item = content[0]["content"][i]
            assert list_item["type"] == "listItem"
            assert list_item["content"][0]["type"] == "paragraph"
            assert list_item["content"][0]["content"][0]["text"] == item_text

        # Ordered list
        markdown_ol = """1. First item
2. Second item
3. Third item"""

        result2 = serializer.from_markdown_to_json(markdown_ol)
        content2 = result2.model_dump()["content"]

        assert len(content2) == 1
        assert content2[0]["type"] == "orderedList"
        assert content2[0]["attrs"]["start"] == 1
        assert len(content2[0]["content"]) == 3

        # Ordered list with custom start
        markdown_ol_start = """5. Fifth item
6. Sixth item"""

        result3 = serializer.from_markdown_to_json(markdown_ol_start)
        content3 = result3.model_dump()["content"]

        assert content3[0]["type"] == "orderedList"
        assert content3[0]["attrs"]["start"] == 5

    def test_markdown_to_json_blockquotes(self):
        """Test markdown blockquote parsing."""
        serializer = NotebookSerializer()

        markdown = """> This is a quote
> with multiple lines
> and more content"""

        result = serializer.from_markdown_to_json(markdown)
        content = result.model_dump()["content"]

        assert len(content) == 1
        assert content[0]["type"] == "blockquote"

        # Blockquote should contain parsed content
        blockquote_content = content[0]["content"]
        assert len(blockquote_content) >= 1

        # Should contain the quote text
        all_text = str(content)
        assert "This is a quote" in all_text
        assert "with multiple lines" in all_text
        assert "and more content" in all_text

    def test_markdown_to_json_horizontal_rules(self):
        """Test markdown horizontal rule parsing."""
        serializer = NotebookSerializer()

        test_cases = ["---", "***", "___"]

        for markdown in test_cases:
            result = serializer.from_markdown_to_json(markdown)
            content = result.model_dump()["content"]

            assert len(content) == 1
            assert content[0]["type"] == "horizontalRule"

    def test_markdown_to_json_inline_formatting(self):
        """Test markdown inline formatting (bold, italic, code, etc.)."""
        serializer = NotebookSerializer()

        markdown = "This has **bold** and *italic* and `code` and ~~strikethrough~~ text."

        result = serializer.from_markdown_to_json(markdown)
        content = result.model_dump()["content"]

        assert len(content) == 1
        assert content[0]["type"] == "paragraph"

        text_nodes = content[0]["content"]

        # Find the bold text
        bold_found = False
        italic_found = False
        code_found = False
        strikethrough_found = False

        for node in text_nodes:
            if node.get("marks"):
                mark_types = {mark["type"] for mark in node["marks"]}
                if "bold" in mark_types and node["text"] == "bold":
                    bold_found = True
                if "italic" in mark_types and node["text"] == "italic":
                    italic_found = True
                if "code" in mark_types and node["text"] == "code":
                    code_found = True
                if "strike" in mark_types and node["text"] == "strikethrough":
                    strikethrough_found = True

        assert bold_found, "Should find bold text with bold mark"
        assert italic_found, "Should find italic text with italic mark"
        assert code_found, "Should find code text with code mark"
        assert strikethrough_found, "Should find strikethrough text with strike mark"

    def test_markdown_to_json_links(self):
        """Test markdown link parsing."""
        serializer = NotebookSerializer()

        markdown = "Check out [PostHog](https://posthog.com) for analytics."

        result = serializer.from_markdown_to_json(markdown)
        content = result.model_dump()["content"]

        assert len(content) == 1
        assert content[0]["type"] == "paragraph"

        text_nodes = content[0]["content"]

        # Find the link
        link_found = False
        for node in text_nodes:
            if node.get("marks"):
                for mark in node["marks"]:
                    if mark["type"] == "link" and mark["attrs"]["href"] == "https://posthog.com":
                        assert node["text"] == "PostHog"
                        assert mark["attrs"]["target"] == "_blank"
                        link_found = True

        assert link_found, "Should find link with proper href and target"

    def test_markdown_to_json_unsafe_links(self):
        """Test that unsafe links are filtered out."""
        serializer = NotebookSerializer()

        unsafe_links = [
            "[XSS](javascript:alert('xss'))",
            "[Data](data:text/html,<script>alert(1)</script>)",
            "[VBScript](vbscript:msgbox(1))",
        ]

        for markdown in unsafe_links:
            result = serializer.from_markdown_to_json(markdown)
            content = result.model_dump()["content"]

            # Link should be present as text but without href
            text_nodes = content[0]["content"]

            # Should not have link marks
            has_link_mark = False
            for node in text_nodes:
                if node.get("marks"):
                    for mark in node["marks"]:
                        if mark["type"] == "link":
                            has_link_mark = True

            assert not has_link_mark, f"Unsafe link should be filtered: {markdown}"

    def test_markdown_to_json_mixed_content(self):
        """Test complex markdown with mixed content types."""
        serializer = NotebookSerializer()

        markdown = """# Main Title

This is a paragraph with **bold** and *italic* text.

## Section

Here's a list:

- First item
- Second item with `code`
- Third item

And a code block:

```python
def hello():
    return "world"
```

> This is a blockquote
> with multiple lines

---

Final paragraph."""

        result = serializer.from_markdown_to_json(markdown)
        content = result.model_dump()["content"]

        # Should have multiple elements
        assert len(content) >= 7

        # Check for expected types
        element_types = [elem["type"] for elem in content]
        assert "heading" in element_types
        assert "paragraph" in element_types
        assert "bulletList" in element_types
        assert "codeBlock" in element_types
        assert "blockquote" in element_types
        assert "horizontalRule" in element_types

    def test_markdown_to_json_nested_formatting(self):
        """Test nested markdown formatting."""
        serializer = NotebookSerializer()

        # Note: Markdown doesn't naturally support nested formatting like ***text***
        # but our parser should handle what it can
        markdown = "This is **bold with *nested italic* inside** text."

        result = serializer.from_markdown_to_json(markdown)
        content = result.model_dump()["content"]

        assert len(content) == 1
        assert content[0]["type"] == "paragraph"

        # Should preserve the text content even if nesting isn't perfect
        all_text = "".join(node.get("text", "") for node in content[0]["content"])
        assert "bold with *nested italic* inside" in all_text

    def test_markdown_to_json_empty_input(self):
        """Test markdown parsing with empty or whitespace-only input."""
        serializer = NotebookSerializer()

        test_cases = ["", "   ", "\n\n", "\t"]

        for markdown in test_cases:
            result = serializer.from_markdown_to_json(markdown)
            content = result.model_dump()["content"]

            # Should produce empty document or no meaningful content
            assert len(content) == 0 or all(
                not elem.get("content")
                or (
                    elem.get("content")
                    and not any(node.get("text", "").strip() for node in elem["content"] if node.get("type") == "text")
                )
                for elem in content
            )

    def test_markdown_to_json_special_characters(self):
        """Test markdown parsing with special characters and edge cases."""
        serializer = NotebookSerializer()

        markdown = """# Title with "quotes" and 'apostrophes'

Paragraph with special chars: & < > " ' and unicode: 😀 🎉

`Code with <tags>` and more text."""

        result = serializer.from_markdown_to_json(markdown)
        content = result.model_dump()["content"]

        # Should preserve special characters
        # Collect all text from the content
        all_text_parts = []
        for node in content:
            if node.get("content"):
                for child in node["content"]:
                    if child.get("text"):
                        all_text_parts.append(child["text"])
        all_text = " ".join(all_text_parts)

        assert '"quotes"' in all_text
        assert "'apostrophes'" in all_text
        assert "&" in all_text
        assert "<" in all_text
        assert ">" in all_text
        assert "😀" in all_text

    def test_markdown_tokenizer_edge_cases(self):
        """Test edge cases in markdown tokenization."""

        tokenizer = MarkdownTokenizer()

        # Test incomplete code block
        markdown = "```python\ncode without closing"
        tokens = tokenizer.tokenize(markdown)

        assert len(tokens) == 1
        assert tokens[0]["type"] == "code_block"
        assert tokens[0]["language"] == "python"
        assert "code without closing" in tokens[0]["content"]

        # Test mixed list markers
        markdown = "- Item 1\n* Item 2\n+ Item 3"
        tokens = tokenizer.tokenize(markdown)

        # Should create separate lists for different markers
        # or handle as one list (implementation dependent)
        assert len(tokens) >= 1
        assert any(token["type"] == "unordered_list" for token in tokens)

    def test_markdown_roundtrip_consistency(self):
        """Test that markdown->JSON->markdown maintains basic structure."""
        serializer = NotebookSerializer()

        original_markdown = """# Title

This is a **bold** paragraph.

- Item 1
- Item 2

```python
code here
```"""

        # Convert to JSON
        json_result = serializer.from_markdown_to_json(original_markdown)

        # Convert back to markdown
        converted_markdown = serializer.from_json_to_markdown(json_result)

        # Should contain key elements (not exact match due to formatting differences)
        assert "# Title" in converted_markdown
        assert "**bold**" in converted_markdown
        assert "- Item 1" in converted_markdown
        assert "- Item 2" in converted_markdown
        assert "```python" in converted_markdown
        assert "code here" in converted_markdown

    def test_markdown_custom_elements_fallback(self):
        """Test that custom HTML elements in markdown are handled gracefully."""
        serializer = NotebookSerializer()

        # Markdown with HTML tags (which should be treated as text)
        markdown = "Regular text and <custom>something</custom> here"

        result = serializer.from_markdown_to_json(markdown)
        content = result.model_dump()["content"]

        assert len(content) == 1
        assert content[0]["type"] == "paragraph"

        # HTML tags should be preserved as text
        all_text = "".join(node.get("text", "") for node in content[0]["content"])
        assert "<custom>something</custom>" in all_text

    def test_json_to_markdown_spacing_after_marks(self):
        """Test that spacing after marks is handled correctly in JSON to markdown conversion."""
        serializer = NotebookSerializer()

        # Create JSON content that was problematic in the user's example
        doc = ProsemirrorJSONContent(
            type="doc",
            content=[
                ProsemirrorJSONContent(
                    type="paragraph",
                    content=[
                        ProsemirrorJSONContent(type="text", text="Insight type: "),
                        ProsemirrorJSONContent(type="text", text="funnel", marks=[Mark(type="italic")]),
                        ProsemirrorJSONContent(type="text", text=" broken down by one dimension at a time"),
                    ],
                )
            ],
        )

        markdown = serializer.from_json_to_markdown(doc)

        # Should have proper spacing between "funnel" and "broken"
        assert "Insight type: *funnel* broken down by one dimension at a time" in markdown
        assert "*funnel*broken" not in markdown  # Should NOT have this pattern

    def test_json_to_markdown_nested_list_indentation(self):
        """Test that nested lists have proper indentation in markdown output."""
        serializer = NotebookSerializer()

        # Create a structure with nested lists like in the user's example
        doc = ProsemirrorJSONContent(
            type="doc",
            content=[
                ProsemirrorJSONContent(
                    type="bulletList",
                    content=[
                        ProsemirrorJSONContent(
                            type="listItem",
                            content=[
                                ProsemirrorJSONContent(
                                    type="paragraph",
                                    content=[ProsemirrorJSONContent(type="text", text="Key moments to track")],
                                )
                            ],
                        ),
                        ProsemirrorJSONContent(
                            type="listItem",
                            content=[
                                ProsemirrorJSONContent(
                                    type="bulletList",
                                    content=[
                                        ProsemirrorJSONContent(
                                            type="listItem",
                                            content=[
                                                ProsemirrorJSONContent(
                                                    type="paragraph",
                                                    content=[
                                                        ProsemirrorJSONContent(
                                                            type="text", text="Entry event", marks=[Mark(type="bold")]
                                                        ),
                                                        ProsemirrorJSONContent(
                                                            type="text", text=": first product visit"
                                                        ),
                                                    ],
                                                )
                                            ],
                                        ),
                                        ProsemirrorJSONContent(
                                            type="listItem",
                                            content=[
                                                ProsemirrorJSONContent(
                                                    type="paragraph",
                                                    content=[
                                                        ProsemirrorJSONContent(
                                                            type="text",
                                                            text="Completion event",
                                                            marks=[Mark(type="bold")],
                                                        ),
                                                        ProsemirrorJSONContent(
                                                            type="text", text=": successful account creation"
                                                        ),
                                                    ],
                                                )
                                            ],
                                        ),
                                    ],
                                )
                            ],
                        ),
                    ],
                )
            ],
        )

        markdown = serializer.from_json_to_markdown(doc)

        # Check that nested lists are properly indented
        lines = markdown.split("\n")

        # Find the nested list items
        entry_line = next((i for i, line in enumerate(lines) if "**Entry event**" in line), -1)
        completion_line = next((i for i, line in enumerate(lines) if "**Completion event**" in line), -1)

        assert entry_line != -1, "Should find Entry event line"
        assert completion_line != -1, "Should find Completion event line"

        # Nested items should be indented with 2 spaces
        assert lines[entry_line].startswith("  -"), f"Entry event should be indented: {lines[entry_line]}"
        assert lines[completion_line].startswith(
            "  -"
        ), f"Completion event should be indented: {lines[completion_line]}"

    def test_markdown_to_json_spacing_preservation(self):
        """Test that spaces between marked text and normal text are preserved correctly."""
        serializer = NotebookSerializer()

        # Test cases with spaces before and after marks
        test_cases = [
            # (markdown input, expected text nodes)
            (
                "Using **trends** first establishes context",
                [("Using ", None), ("trends", ["bold"]), (" first establishes context", None)],
            ),
            ("**foo** bar _baz_", [("foo", ["bold"]), (" bar ", None), ("baz", ["italic"])]),
            ("Text with `code` and more", [("Text with ", None), ("code", ["code"]), (" and more", None)]),
            (
                "Multiple **bold** and **more** text",
                [("Multiple ", None), ("bold", ["bold"]), (" and ", None), ("more", ["bold"]), (" text", None)],
            ),
        ]

        for markdown, expected_nodes in test_cases:
            result = serializer.from_markdown_to_json(markdown)
            content = result.model_dump()["content"]

            assert len(content) == 1
            assert content[0]["type"] == "paragraph"

            text_nodes = content[0]["content"]

            # Verify the number of text nodes matches expected
            assert len(text_nodes) == len(
                expected_nodes
            ), f"Expected {len(expected_nodes)} nodes for '{markdown}', got {len(text_nodes)}"

            # Verify each text node
            for i, (expected_text, expected_marks) in enumerate(expected_nodes):
                node = text_nodes[i]
                assert node["type"] == "text"
                assert node["text"] == expected_text, f"Node {i}: expected text '{expected_text}', got '{node['text']}'"

                if expected_marks:
                    assert node.get("marks"), f"Node {i}: expected marks but got none"
                    mark_types = [mark["type"] for mark in node["marks"]]
                    assert mark_types == expected_marks, f"Node {i}: expected marks {expected_marks}, got {mark_types}"
                else:
                    assert not node.get("marks"), f"Node {i}: expected no marks but got {node.get('marks')}"

    def test_assistant_query_conversion_to_insight_viz_node(self):
        """Test that AssistantQuery objects are properly converted to InsightVizNode format for frontend compatibility."""
        # Test AssistantTrendsQuery conversion
        assistant_trends_query = AssistantTrendsQuery(kind="TrendsQuery", series=[])

        serializer = NotebookSerializer()
        converted = serializer._convert_assistant_query_to_insight_viz_node(assistant_trends_query)

        assert isinstance(converted, dict), "Converted query should be a dict"
        assert converted["kind"] == "InsightVizNode", "Should wrap AssistantQuery in InsightVizNode"
        assert converted["source"].kind == "TrendsQuery", "Source should be converted to regular TrendsQuery"
        assert type(converted["source"]).__name__ == "TrendsQuery", "Source should be TrendsQuery type"

        # Test AssistantFunnelsQuery conversion
        assistant_funnels_query = AssistantFunnelsQuery(kind="FunnelsQuery", series=[])

        converted_funnels = serializer._convert_assistant_query_to_insight_viz_node(assistant_funnels_query)

        assert isinstance(converted_funnels, dict), "Converted funnel query should be a dict"
        assert converted_funnels["kind"] == "InsightVizNode", "Should wrap AssistantFunnelsQuery in InsightVizNode"
        assert converted_funnels["source"].kind == "FunnelsQuery", "Source should be converted to regular FunnelsQuery"
        assert type(converted_funnels["source"]).__name__ == "FunnelsQuery", "Source should be FunnelsQuery type"

        assistant_hogql_query = AssistantHogQLQuery(kind="HogQLQuery", query="SELECT * FROM events")

        converted_hogql = serializer._convert_assistant_query_to_insight_viz_node(assistant_hogql_query)

        assert isinstance(converted_hogql, dict), "Converted HogQL query should be a dict"
        assert (
            converted_hogql["kind"] == "DataTableNode"
        ), "Should wrap AssistantHogQLQuery in DataTableNode, NOT InsightVizNode"
        assert converted_hogql["source"].kind == "HogQLQuery", "Source should be converted to regular HogQLQuery"
        assert type(converted_hogql["source"]).__name__ == "HogQLQuery", "Source should be HogQLQuery type"

        # Test that non-Assistant queries pass through unchanged
        regular_query = {"kind": "InsightVizNode", "source": {"kind": "TrendsQuery"}}
        unchanged = serializer._convert_assistant_query_to_insight_viz_node(regular_query)

        assert unchanged == regular_query, "Non-Assistant queries should pass through unchanged"

    def test_ph_query_node_creation_with_assistant_query(self):
        """Test that ph-query nodes are properly created with InsightVizNode wrapping for AssistantQuery objects."""
        # Create an AssistantTrendsQuery
        assistant_query = AssistantTrendsQuery(kind="TrendsQuery", series=[])

        # Create an InsightArtifact with the AssistantQuery
        artifact = InsightArtifact(
            id=None, task_id="test-insight-1", query=assistant_query, content="Test trends query"
        )

        # Create context and serializer
        context = NotebookContext(insights={"test-insight-1": artifact})
        serializer = NotebookSerializer(context=context)

        # Create ph-query node
        ph_query_node = serializer._create_ph_query_node("test-insight-1")

        assert ph_query_node is not None, "Should create a ph-query node"
        assert ph_query_node.type == "ph-query", "Should have ph-query type"
        assert "query" in cast(dict, ph_query_node.attrs), "Should have query in attrs"

        query_attr = cast(dict, ph_query_node.attrs)["query"]
        assert isinstance(query_attr, dict), "Query attr should be a dict"
        assert query_attr["kind"] == "InsightVizNode", "Query should be wrapped in InsightVizNode"
        assert "source" in query_attr, "Query should have source field"
        assert query_attr["source"].kind == "TrendsQuery", "Source should be converted to regular TrendsQuery"
        assert type(query_attr["source"]).__name__ == "TrendsQuery", "Source should be TrendsQuery type"

    def test_markdown_to_json_with_insight_tags_uses_insight_viz_node(self):
        """Test that markdown with insight tags creates ph-query nodes with proper InsightVizNode structure."""
        # Create an AssistantTrendsQuery
        assistant_query = AssistantTrendsQuery(kind="TrendsQuery", series=[])

        # Create artifact and context
        artifact = InsightArtifact(
            id=None, task_id="test-insight-123", query=assistant_query, content="Test insight for markdown conversion"
        )
        context = NotebookContext(insights={"test-insight-123": artifact})
        serializer = NotebookSerializer(context=context)

        # Test markdown with insight tag
        markdown = "Analysis shows:\n\n<insight>test-insight-123</insight>\n\nThis demonstrates the trend."

        # Convert to JSON
        prosemirror_json = serializer.from_markdown_to_json(markdown)

        # Verify structure
        assert prosemirror_json.type == "doc", "Should be a document"
        assert prosemirror_json.content, "Document should have content"

        # Find the ph-query node
        ph_query_node = None
        for node in prosemirror_json.content:
            if node.type == "ph-query":
                ph_query_node = node
                break

        assert ph_query_node is not None, "Should find a ph-query node in the converted content"
        assert "query" in cast(dict, ph_query_node.attrs), "ph-query node should have query attr"

        query_attr = cast(dict, ph_query_node.attrs)["query"]
        assert isinstance(query_attr, dict), "Query attr should be a dict"
        assert query_attr["kind"] == "InsightVizNode", "Should have InsightVizNode structure"
        assert "source" in query_attr, "Should have source field"
        assert query_attr["source"].kind == "TrendsQuery", "Source should be converted to regular TrendsQuery"
        assert type(query_attr["source"]).__name__ == "TrendsQuery", "Source should be TrendsQuery type"

    def test_deep_research_report_query_visualization_crash_fix(self):
        """Test that the specific crash scenario from deep research reports is fixed.

        This test simulates the exact scenario where:
        1. Deep research creates InsightArtifact with AssistantQuery
        2. Report node passes it to notebook serializer
        3. Frontend expects InsightVizNode format but was getting raw AssistantQuery

        This test ensures the crash is fixed by verifying the full pipeline works.
        """
        # Simulate the deep research report scenario
        # 1. Create an AssistantQuery like the report node would generate
        assistant_trends_query = AssistantTrendsQuery(
            kind="TrendsQuery", series=[AssistantTrendsEventsNode(kind="EventsNode", event="$pageview", math="total")]
        )

        # 2. Create InsightArtifact like DeepResearchReportNode._create_context() does
        insight_artifact = InsightArtifact(
            id=None,
            task_id="crash-test-insight",
            query=assistant_trends_query,  # This was causing the crash
            content="Test query that was crashing frontend visualization",
        )

        # 3. Create context like report node does
        context = NotebookContext(insights={"crash-test-insight": insight_artifact})
        serializer = NotebookSerializer(context=context)

        # 4. Simulate report generating markdown with insight tag
        report_markdown = """# Deep Research Report

Based on the analysis, here are the key findings:

<insight>crash-test-insight</insight>

The data shows clear trends in user behavior."""

        # 5. Convert to JSON (this is where the crash would happen)
        try:
            prosemirror_json = serializer.from_markdown_to_json(report_markdown)
            conversion_successful = True
        except Exception:
            conversion_successful = False

        # 6. Verify conversion succeeded (no crash)
        assert conversion_successful, "Notebook serialization should not crash with AssistantQuery"

        # 7. Verify the output has the correct structure for frontend
        assert prosemirror_json.type == "doc"
        assert prosemirror_json.content is not None

        # Find the ph-query node that would be sent to frontend
        ph_query_node = None
        for node in prosemirror_json.content:
            if node.type == "ph-query":
                ph_query_node = node
                break

        assert ph_query_node is not None, "Should create ph-query node for insight"

        # 8. Verify the ph-query has the format frontend expects (preventing visualization crash)
        query_data = cast(dict, ph_query_node.attrs)["query"]

        # This is the key fix - query must be wrapped in InsightVizNode
        assert isinstance(query_data, dict), "Query data should be a dict"
        assert query_data["kind"] == "InsightVizNode", "Query must be wrapped in InsightVizNode for frontend"
        assert "source" in query_data, "InsightVizNode must have source field"
        assert query_data["source"].kind == "TrendsQuery", "Source should be converted to regular TrendsQuery"
        assert type(query_data["source"]).__name__ == "TrendsQuery", "Source should be TrendsQuery type"

        # 9. Verify this matches the format frontend expects (like in notebook templates)
        # The frontend expects this structure based on migrate.test.ts examples:
        # { "kind": "InsightVizNode", "source": { "kind": "TrendsQuery", ... } }
        assert query_data["source"].kind == "TrendsQuery", "Source should maintain TrendsQuery kind"

        # 10. This test proves the crash is fixed:
        # - Before fix: ph-query node would have raw AssistantQuery causing frontend crash
        # - After fix: ph-query node has InsightVizNode wrapper that frontend can handle

    def test_converted_query_caching(self):
        """Test that converted queries are cached to avoid repeated conversions during streaming."""
        assistant_query = AssistantTrendsQuery(kind="TrendsQuery", series=[])
        serializer = NotebookSerializer()

        # First conversion should log and cache
        result1 = serializer._convert_assistant_query_to_insight_viz_node(assistant_query)

        # Verify cache is populated
        query_id = id(assistant_query)
        assert query_id in serializer._converted_query_cache
        assert serializer._converted_query_cache[query_id] == result1

        # Second conversion should use cache (same object reference)
        result2 = serializer._convert_assistant_query_to_insight_viz_node(assistant_query)

        # Should return the exact same cached object
        assert result2 is result1
        assert result2 == result1

        # Verify structure is correct
        assert result2["kind"] == "InsightVizNode"
        # The source should now be a regular TrendsQuery, not the original AssistantTrendsQuery
        assert result2["source"].kind == "TrendsQuery"
        assert type(result2["source"]).__name__ == "TrendsQuery"

    def test_cast_assistant_query(self):
        """Test that cast_assistant_query properly converts AssistantQuery types to regular Query types."""
        # Test AssistantTrendsQuery -> TrendsQuery
        assistant_trends = AssistantTrendsQuery(kind="TrendsQuery", series=[])
        regular_trends = cast_assistant_query(assistant_trends)
        assert type(regular_trends).__name__ == "TrendsQuery"
        assert regular_trends.kind == "TrendsQuery"

        # Test AssistantFunnelsQuery -> FunnelsQuery
        assistant_funnels = AssistantFunnelsQuery(kind="FunnelsQuery", series=[])
        regular_funnels = cast_assistant_query(assistant_funnels)
        assert type(regular_funnels).__name__ == "FunnelsQuery"
        assert regular_funnels.kind == "FunnelsQuery"

        # Test AssistantHogQLQuery -> HogQLQuery
        assistant_hogql = AssistantHogQLQuery(kind="HogQLQuery", query="SELECT 1")
        regular_hogql = cast_assistant_query(assistant_hogql)
        assert type(regular_hogql).__name__ == "HogQLQuery"
        assert regular_hogql.kind == "HogQLQuery"
        assert regular_hogql.query == "SELECT 1"

        # Test unsupported query type
        class UnsupportedQuery:
            def __init__(self):
                self.kind = "UnsupportedQuery"

        with self.assertRaises(ValueError) as context:
            cast_assistant_query(UnsupportedQuery())  # type: ignore
        assert "Unsupported query type: UnsupportedQuery" in str(context.exception)
