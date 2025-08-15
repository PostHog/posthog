import re
import logging
from urllib.parse import urlparse, unquote
from typing import Optional

from posthog.schema import ProsemirrorJSONContent, Mark

logger = logging.getLogger(__name__)


class MarkdownTokenizer:
    """Simple markdown tokenizer that handles the most common markdown elements."""

    def __init__(self):
        self.tokens = []
        self.pos = 0
        self.text = ""

    def tokenize(self, text: str) -> list[dict]:
        """Tokenize markdown text into a list of tokens."""
        self.text = text
        self.pos = 0
        self.tokens = []

        while self.pos < len(self.text):
            if not self._try_parse_block_element():
                # If no block element found, parse as paragraph
                self._parse_paragraph()

        return self.tokens

    def _try_parse_block_element(self) -> bool:
        """Try to parse a block-level element. Returns True if successful."""
        # Skip empty lines
        if self._at_line_start() and self._current_line().strip() == "":
            self._skip_line()
            return True

        # Try different block elements
        if self._try_parse_heading():
            return True
        if self._try_parse_code_block():
            return True
        if self._try_parse_blockquote():
            return True
        if self._try_parse_horizontal_rule():
            return True
        if self._try_parse_list():
            return True

        return False

    def _try_parse_heading(self) -> bool:
        """Parse heading (# ## ### etc)."""
        if not self._at_line_start():
            return False

        line = self._current_line()
        match = re.match(r"^(#{1,6})\s+(.+)$", line)
        if match:
            level = len(match.group(1))
            content = match.group(2).strip()
            self.tokens.append({"type": "heading", "level": level, "content": content})
            self._skip_line()
            return True
        return False

    def _try_parse_code_block(self) -> bool:
        """Parse fenced code block (``` language)."""
        if not self._at_line_start():
            return False

        line = self._current_line()
        match = re.match(r"^```(\w*)\s*$", line)
        if match:
            language = match.group(1) or None
            self._skip_line()

            # Collect code lines until closing ``` or EOF
            code_lines = []
            while self.pos < len(self.text):
                line = self._current_line()
                if line.strip() == "```":
                    self._skip_line()
                    break
                code_lines.append(line)
                self._skip_line()

            # Add the code block even if no closing fence was found (treat EOF as implicit close)
            self.tokens.append({"type": "code_block", "language": language, "content": "\n".join(code_lines)})
            return True
        return False

    def _try_parse_blockquote(self) -> bool:
        """Parse blockquote (> text)."""
        if not self._at_line_start():
            return False

        line = self._current_line()
        match = re.match(r"^>\s*(.*)$", line)
        if match:
            # Collect all consecutive blockquote lines
            quote_lines = []
            while self.pos < len(self.text):
                line_match = re.match(r"^>\s*(.*)$", self._current_line())
                if line_match:
                    quote_lines.append(line_match.group(1))
                    self._skip_line()
                else:
                    break

            self.tokens.append({"type": "blockquote", "content": "\n".join(quote_lines)})
            return True
        return False

    def _try_parse_horizontal_rule(self) -> bool:
        """Parse horizontal rule (--- or ***)."""
        if not self._at_line_start():
            return False

        line = self._current_line().strip()
        if re.match(r"^(-{3,}|\*{3,}|_{3,})$", line):
            self.tokens.append({"type": "horizontal_rule"})
            self._skip_line()
            return True
        return False

    def _try_parse_list(self) -> bool:
        """Parse ordered or unordered list."""
        if not self._at_line_start():
            return False

        line = self._current_line()

        # Check for unordered list (- * +)
        unordered_match = re.match(r"^(\s*)([-*+])\s+(.+)$", line)
        if unordered_match:
            return self._parse_list_items("unordered", unordered_match.group(1))

        # Check for ordered list (1. 2. etc)
        ordered_match = re.match(r"^(\s*)(\d+)\.\s+(.+)$", line)
        if ordered_match:
            start_num = int(ordered_match.group(2))
            return self._parse_list_items("ordered", ordered_match.group(1), start_num)

        return False

    def _parse_list_items(self, list_type: str, base_indent: str, start: int = 1) -> bool:
        """Parse consecutive list items."""
        items: list[str] = []

        while self.pos < len(self.text):
            line = self._current_line()

            if list_type == "unordered":
                match = re.match(rf"^{re.escape(base_indent)}[-*+]\s+(.+)$", line)
            else:
                match = re.match(rf"^{re.escape(base_indent)}\d+\.\s+(.+)$", line)

            if match:
                items.append(match.group(1))
                self._skip_line()
            else:
                break

        if items:
            token: dict[str, str | int | list[str]] = {"type": list_type + "_list", "items": items}
            if list_type == "ordered":
                token["start"] = start
            self.tokens.append(token)
            return True

        return False

    def _parse_paragraph(self) -> None:
        """Parse a paragraph (everything else)."""
        if self.pos >= len(self.text):
            return

        # Collect lines until we hit a blank line or end
        para_lines = []

        while self.pos < len(self.text):
            line = self._current_line()

            # Stop at blank line
            if line.strip() == "":
                break

            # Stop if we hit a block element at line start
            if self._at_line_start() and self._looks_like_block_element(line):
                break

            para_lines.append(line)
            self._skip_line()

        if para_lines:
            content = " ".join(line.strip() for line in para_lines).strip()
            if content:
                self.tokens.append({"type": "paragraph", "content": content})

    def _looks_like_block_element(self, line: str) -> bool:
        """Check if a line looks like the start of a block element."""
        line = line.strip()
        return (
            bool(re.match(r"^#{1,6}\s+", line))  # heading
            or line.startswith("```")  # code block
            or bool(re.match(r"^>\s*", line))  # blockquote
            or bool(re.match(r"^(-{3,}|\*{3,}|_{3,})$", line))  # horizontal rule
            or bool(re.match(r"^(\s*)([-*+]|\d+\.)\s+", line))  # list
        )

    def _current_line(self) -> str:
        """Get the current line from position."""
        if self.pos >= len(self.text):
            return ""

        end = self.text.find("\n", self.pos)
        if end == -1:
            return self.text[self.pos :]
        return self.text[self.pos : end]

    def _skip_line(self) -> None:
        """Move to the next line."""
        end = self.text.find("\n", self.pos)
        if end == -1:
            self.pos = len(self.text)
        else:
            self.pos = end + 1

    def _at_line_start(self) -> bool:
        """Check if we're at the start of a line."""
        return self.pos == 0 or (self.pos > 0 and self.text[self.pos - 1] == "\n")


class NotebookSerializer:
    # Allowed URL schemes for security
    ALLOWED_SCHEMES = {"http", "https", "mailto", "tel"}

    # Tags that map to marks - only officially supported marks in @tiptap/starter-kit
    MARK_TAGS = {
        "strong": "bold",
        "b": "bold",
        "em": "italic",
        "i": "italic",
        "u": "underline",
        "s": "strike",
        "del": "strike",
        "strike": "strike",
        "code": "code",
    }

    # Pre-compiled inline markdown patterns for performance
    INLINE_PATTERNS = [
        # Bold: **text** or __text__ - check these first to prioritize over italic
        (re.compile(r"\*\*(.+?)\*\*"), "bold"),
        (re.compile(r"__(.*?)__"), "bold"),
        # Italic: *text* or _text_
        (re.compile(r"\*(.*?)\*"), "italic"),
        (re.compile(r"_(.*?)_"), "italic"),
        # Code: `text`
        (re.compile(r"`(.*?)`"), "code"),
        # Strikethrough: ~~text~~
        (re.compile(r"~~(.*?)~~"), "strikethrough"),
        # Link: [text](url)
        (re.compile(r"\[([^\]]*)\]\(([^)]*)\)"), "link"),
    ]

    def to_json_paragraph(self, input: str | list[ProsemirrorJSONContent]) -> ProsemirrorJSONContent:
        return ProsemirrorJSONContent(
            type="paragraph",
            content=input if isinstance(input, list) else [ProsemirrorJSONContent(type="text", text=input)],
        )

    def to_json_heading(self, input: str | list[ProsemirrorJSONContent], level: int) -> ProsemirrorJSONContent:
        return ProsemirrorJSONContent(
            type="heading",
            attrs={"level": level},
            content=input if isinstance(input, list) else [ProsemirrorJSONContent(type="text", text=input)],
        )

    def to_json_bullet_list(self, items: list[ProsemirrorJSONContent]) -> ProsemirrorJSONContent:
        return ProsemirrorJSONContent(type="bulletList", content=items)

    def to_json_ordered_list(self, items: list[ProsemirrorJSONContent], start: int = 1) -> ProsemirrorJSONContent:
        return ProsemirrorJSONContent(type="orderedList", attrs={"start": start}, content=items)

    def to_json_list_item(self, content: list[ProsemirrorJSONContent]) -> ProsemirrorJSONContent:
        return ProsemirrorJSONContent(type="listItem", content=content)

    def to_json_code_block(self, code: str, language: str | None = None) -> ProsemirrorJSONContent:
        attrs = {"language": language} if language else {}
        return ProsemirrorJSONContent(
            type="codeBlock", attrs=attrs, content=[ProsemirrorJSONContent(type="text", text=code)]
        )

    def to_json_blockquote(self, content: list[ProsemirrorJSONContent]) -> ProsemirrorJSONContent:
        return ProsemirrorJSONContent(type="blockquote", content=content)

    def to_json_horizontal_rule(self) -> ProsemirrorJSONContent:
        return ProsemirrorJSONContent(type="horizontalRule")

    def from_markdown_to_json(self, input: str) -> ProsemirrorJSONContent:
        """
        Parse markdown and convert to TipTap notebook schema.
        """
        # Tokenize the markdown
        tokenizer = MarkdownTokenizer()
        tokens = tokenizer.tokenize(input)

        # Convert tokens to ProsemirrorJSONContent
        json_result: list[ProsemirrorJSONContent] = []
        for token in tokens:
            nodes = self._convert_markdown_token(token)
            json_result.extend(nodes)

        return ProsemirrorJSONContent(type="doc", content=json_result)

    def _convert_markdown_token(self, token: dict) -> list[ProsemirrorJSONContent]:
        """Convert a markdown token to ProsemirrorJSONContent nodes."""
        token_type = token["type"]

        if token_type == "paragraph":
            content = self._parse_markdown_inline_content(token["content"])
            return [self.to_json_paragraph(content)]

        elif token_type == "heading":
            content = self._parse_markdown_inline_content(token["content"])
            return [self.to_json_heading(content, token["level"])]

        elif token_type == "code_block":
            return [self.to_json_code_block(token["content"], token.get("language"))]

        elif token_type == "blockquote":
            # Parse blockquote content as markdown and convert to block content
            quote_content = self._parse_blockquote_content(token["content"])
            return [self.to_json_blockquote(quote_content)]

        elif token_type == "horizontal_rule":
            return [self.to_json_horizontal_rule()]

        elif token_type == "unordered_list":
            items = []
            for item_text in token["items"]:
                item_content = self._parse_markdown_inline_content(item_text)
                items.append(self.to_json_list_item([self.to_json_paragraph(item_content)]))
            return [self.to_json_bullet_list(items)]

        elif token_type == "ordered_list":
            items = []
            for item_text in token["items"]:
                item_content = self._parse_markdown_inline_content(item_text)
                items.append(self.to_json_list_item([self.to_json_paragraph(item_content)]))
            start = token.get("start", 1)
            return [self.to_json_ordered_list(items, start)]

        return []

    def _parse_markdown_inline_content(self, text: str) -> list[ProsemirrorJSONContent]:
        """Parse inline markdown content (bold, italic, links, etc.)."""
        if not text:
            return []

        # This is a simplified inline parser - handles basic formatting
        content = []
        pos = 0

        while pos < len(text):
            # Look for markdown patterns
            next_match = self._find_next_markdown_pattern(text, pos)

            if next_match is None:
                # No more patterns, add remaining text
                remaining = text[pos:].rstrip()
                if remaining:
                    content.append(ProsemirrorJSONContent(type="text", text=remaining))
                break

            match_start, match_end, pattern_type, pattern_data = next_match

            # Add text before the pattern
            if match_start > pos:
                before_text = text[pos:match_start]
                if before_text:
                    content.append(ProsemirrorJSONContent(type="text", text=before_text))

            # Add the formatted content
            if pattern_type == "bold":
                inner_text = pattern_data["text"]
                content.append(ProsemirrorJSONContent(type="text", text=inner_text, marks=[Mark(type="bold")]))
            elif pattern_type == "italic":
                inner_text = pattern_data["text"]
                content.append(ProsemirrorJSONContent(type="text", text=inner_text, marks=[Mark(type="italic")]))
            elif pattern_type == "code":
                inner_text = pattern_data["text"]
                content.append(ProsemirrorJSONContent(type="text", text=inner_text, marks=[Mark(type="code")]))
            elif pattern_type == "strikethrough":
                inner_text = pattern_data["text"]
                content.append(ProsemirrorJSONContent(type="text", text=inner_text, marks=[Mark(type="strike")]))
            elif pattern_type == "link":
                link_text = pattern_data["text"]
                href = pattern_data["href"]
                if self._is_safe_url(href):
                    content.append(
                        ProsemirrorJSONContent(
                            type="text",
                            text=link_text,
                            marks=[Mark(type="link", attrs={"href": href, "target": "_blank"})],
                        )
                    )
                else:
                    # Unsafe URL, just add as text
                    content.append(ProsemirrorJSONContent(type="text", text=link_text))

            pos = match_end

        return content if content else [ProsemirrorJSONContent(type="text", text=text)]

    def _find_next_markdown_pattern(self, text: str, start_pos: int) -> Optional[tuple[int, int, str, dict]]:
        """Find the next markdown formatting pattern in text."""
        earliest_match = None
        earliest_pos = len(text)

        for pattern, pattern_type in self.INLINE_PATTERNS:
            match = pattern.search(text, start_pos)
            if match:
                match_start = match.start()
                match_end = match.end()

                if match_start < earliest_pos:
                    earliest_pos = match_start
                    if pattern_type == "link":
                        earliest_match = (
                            match_start,
                            match_end,
                            pattern_type,
                            {"text": match.group(1), "href": match.group(2)},
                        )
                    else:
                        earliest_match = (match_start, match_end, pattern_type, {"text": match.group(1)})

        return earliest_match

    def _parse_blockquote_content(self, content: str) -> list[ProsemirrorJSONContent]:
        """Parse blockquote content as nested markdown."""
        # Recursively parse the blockquote content as markdown
        tokenizer = MarkdownTokenizer()
        tokens = tokenizer.tokenize(content)

        result = []
        for token in tokens:
            nodes = self._convert_markdown_token(token)
            result.extend(nodes)

        return result if result else [self.to_json_paragraph("")]

    def _is_safe_url(self, url: str) -> bool:
        """Check if URL is safe (no javascript:, data:, etc)."""
        if not url:
            return False

        try:
            # Recursively decode URL until fully decoded to prevent double-encoded attacks
            decoded_url = url.lower()
            max_decode_iterations = 10  # Prevent infinite loops

            for _ in range(max_decode_iterations):
                prev_decoded = decoded_url
                decoded_url = unquote(decoded_url)
                # Stop if no more decoding is happening
                if decoded_url == prev_decoded:
                    break

            # Check the fully decoded URL for dangerous schemes
            parsed = urlparse(decoded_url)

            # Also check the original URL
            parsed_original = urlparse(url.lower())

            return (parsed.scheme in self.ALLOWED_SCHEMES or not parsed.scheme) and (
                parsed_original.scheme in self.ALLOWED_SCHEMES or not parsed_original.scheme
            )
        except Exception:
            return False

    def from_json_to_markdown(self, input: ProsemirrorJSONContent) -> str:
        """
        Convert ProsemirrorJSONContent to markdown.
        """
        if input.type == "doc" and input.content:
            return "\n\n".join(self._convert_node_to_markdown(node) for node in input.content)
        return ""

    def _convert_node_to_markdown(self, node: ProsemirrorJSONContent) -> str:
        """Convert a single node to markdown."""
        if node.type == "paragraph":
            return self._convert_inline_content_to_markdown(node.content or [])

        elif node.type == "heading":
            level = node.attrs.get("level", 1) if node.attrs else 1
            content = self._convert_inline_content_to_markdown(node.content or [])
            return f"{'#' * level} {content}"

        elif node.type == "bulletList":
            return self._convert_list_to_markdown(node.content or [], ordered=False)

        elif node.type == "orderedList":
            start = node.attrs.get("start", 1) if node.attrs else 1
            return self._convert_list_to_markdown(node.content or [], ordered=True, start=start)

        elif node.type == "blockquote":
            lines = []
            for child in node.content or []:
                child_md = self._convert_node_to_markdown(child)
                for line in child_md.split("\n"):
                    lines.append(f"> {line}")
            return "\n".join(lines)

        elif node.type == "codeBlock":
            language = node.attrs.get("language", "") if node.attrs else ""
            code = self._convert_inline_content_to_markdown(node.content or [])
            return f"```{language}\n{code}\n```"

        elif node.type == "horizontalRule":
            return "---"

        elif node.type == "image":
            if not node.attrs:
                return ""
            src = node.attrs.get("src", "")
            alt = node.attrs.get("alt", "")
            title = node.attrs.get("title", "")
            if title:
                return f'![{alt}]({src} "{title}")'
            return f"![{alt}]({src})"

        # Table nodes are not supported

        elif node.type == "text":
            return node.text or ""

        return ""

    def _convert_inline_content_to_markdown(self, content: list[ProsemirrorJSONContent]) -> str:
        """Convert inline content (text with marks) to markdown."""
        result = []
        for i, node in enumerate(content):
            if node.type == "text":
                text = node.text or ""
                if node.marks:
                    # Apply marks in reverse order to handle nested marks correctly
                    for mark in reversed(node.marks):
                        text = self._apply_mark_to_text(text, mark)
                result.append(text)

                # Add space after marked text if needed for word boundaries
                if i < len(content) - 1 and node.marks:
                    next_node = content[i + 1]
                    if next_node.type == "text" and next_node.text:
                        # Only add space if next text doesn't start with space or punctuation
                        first_char = next_node.text[0]
                        if not first_char.isspace() and first_char.isalnum():
                            result.append(" ")

        return "".join(result)

    def _apply_mark_to_text(self, text: str, mark: Mark) -> str:
        """Apply a mark to text."""
        if mark.type == "bold":
            return f"**{text}**"
        elif mark.type == "italic":
            return f"*{text}*"
        elif mark.type == "code":
            return f"`{text}`"
        elif mark.type == "strike":
            return f"~~{text}~~"
        elif mark.type == "underline":
            # Markdown doesn't have native underline, use HTML
            return f"<u>{text}</u>"
        elif mark.type == "link":
            href = mark.attrs.get("href", "") if mark.attrs else ""
            return f"[{text}]({href})"
        # Unsupported marks are ignored
        return text

    def _convert_list_to_markdown(
        self, items: list[ProsemirrorJSONContent], ordered: bool, start: int = 1, level: int = 0
    ) -> str:
        """Convert list items to markdown."""
        lines = []
        for i, item in enumerate(items):
            if item.type == "listItem" and item.content:
                indent = "  " * level
                if ordered:
                    prefix = f"{start + i}."
                else:
                    prefix = "-"

                # Process list item content
                item_lines = []
                for j, child in enumerate(item.content):
                    if child.type == "paragraph":
                        content = self._convert_inline_content_to_markdown(child.content or [])
                        if j == 0:
                            item_lines.append(f"{indent}{prefix} {content}")
                        else:
                            # Additional paragraphs in list items need proper indentation
                            item_lines.append(f"{indent}  {content}")
                    elif child.type in ("bulletList", "orderedList"):
                        # Nested list - ensure proper indentation
                        nested_md = self._convert_list_to_markdown(
                            child.content or [],
                            ordered=(child.type == "orderedList"),
                            start=child.attrs.get("start", 1) if child.attrs else 1,
                            level=level + 1,
                        )
                        # Add nested list directly without extra blank line
                        item_lines.append(nested_md)
                    else:
                        # Other block content in list item
                        child_md = self._convert_node_to_markdown(child)
                        for line in child_md.split("\n"):
                            item_lines.append(f"{indent}  {line}")

                lines.extend(item_lines)

        return "\n".join(lines)
