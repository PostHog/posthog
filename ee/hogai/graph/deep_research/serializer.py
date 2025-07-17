import logging
import xml.etree.ElementTree as ET
from typing import Any
from html import unescape

from posthog.models.notebook.notebook import Notebook

logger = logging.getLogger(__name__)


class DeepResearchSerializer:
    async def save_to_notebook(
        self, notebook: Notebook, report: str, insights_map: dict[str, str], overwrite: bool = False
    ) -> tuple[list[dict[str, Any]], str] | tuple[None, None]:
        json_result, markdown_result = self._parse_report(report, insights_map)
        if json_result and markdown_result:
            if not notebook.content:
                notebook.content = {"type": "doc", "content": []}
            if overwrite:
                notebook.content["content"] = {
                    "type": "doc",
                    "content": [notebook.content["content"][0], *json_result],
                }  # first element is the title
                notebook.text_content = markdown_result
            else:
                notebook.content["content"].extend(json_result)
                if notebook.text_content:
                    notebook.text_content += "\n" + markdown_result
                else:
                    notebook.text_content = markdown_result
            await notebook.asave()
            return json_result, markdown_result
        else:
            logger.error("Failed to parse report")
            return None, None

    def _parse_report(
        self, report: str, insights_map: dict[str, str]
    ) -> tuple[list[dict[str, Any]], str] | tuple[None, None]:
        """
        Parse the AI report markup and convert it to a TipTap notebook schema.

        Converts:
        - <h3>Title</h3> -> heading node (level 1)
        - <p>HTML text with marks</p> -> paragraph node with HTML content and marks
        - <visualization_id>visualization_id</visualization_id> -> query node with SavedInsightNode

        Supports marks: bold, italic, links, underline, strikethrough, code
        """
        try:
            # Parse the XML-like markup
            root = ET.fromstring(f"<root>{report}</root>")
            markdown_results = []

            # Build the TipTap content array
            json_result = []

            for element in root:
                if element.tag == "h1":
                    content = self._parse_element_content(element)
                    if content:
                        json_result.append({"type": "heading", "attrs": {"level": 1}, "content": content})
                        markdown_results.append(f"# {self._element_to_markdown(element)}")
                elif element.tag == "h2":
                    content = self._parse_element_content(element)
                    if content:
                        json_result.append({"type": "heading", "attrs": {"level": 2}, "content": content})
                        markdown_results.append(f"## {self._element_to_markdown(element)}")
                elif element.tag == "h3":
                    content = self._parse_element_content(element)
                    if content:
                        json_result.append({"type": "heading", "attrs": {"level": 3}, "content": content})
                        markdown_results.append(f"# {self._element_to_markdown(element)}")
                elif element.tag == "p":
                    content = self._parse_element_content(element)
                    if content:
                        json_result.append({"type": "paragraph", "content": content})
                        markdown_results.append(f"{self._element_to_markdown(element)}")
                elif element.tag == "visualization":
                    id_element = element.find("id")
                    description_element = element.find("description")
                    if id_element and id_element.text and description_element and description_element.text:
                        query = insights_map[id_element.text]
                        json_result.append(
                            {
                                "type": "ph-query",
                                "attrs": {
                                    "query": query,
                                    "id": id_element.text,
                                },
                            }
                        )
                        markdown_results.append(
                            f"\nVisualization ID: {id_element.text}\nDescription: {description_element.text}\n"
                        )

            return json_result, "\n".join(markdown_results)

        except ET.ParseError as e:
            logger.exception("Failed to parse report", exc_info=e)
            return None, None

    def _parse_element_content(self, element: ET.Element) -> list[dict[str, Any]]:
        """Parse an XML element and its children into ProseMirror content with marks."""
        content = []

        # Handle text before first child
        if element.text:
            content.append({"type": "text", "text": unescape(element.text)})

        # Process child elements
        for child in element:
            child_content = self._parse_child_element(child)
            if child_content:
                content.extend(child_content)

            # Handle tail text after child
            if child.tail:
                content.append({"type": "text", "text": unescape(child.tail)})

        return content

    def _parse_child_element(self, element: ET.Element) -> list[dict[str, Any]]:
        """Parse a child element and convert it to ProseMirror text with marks."""
        marks = []

        # Map HTML tags to ProseMirror marks
        mark_mapping = {
            "strong": {"type": "bold"},
            "b": {"type": "bold"},
            "em": {"type": "italic"},
            "i": {"type": "italic"},
            "u": {"type": "underline"},
            "s": {"type": "strike"},
            "del": {"type": "strike"},
            "code": {"type": "code"},
        }

        # Handle links separately as they have attributes
        if element.tag == "a":
            href = element.get("href")
            if href:
                marks.append({"type": "link", "attrs": {"href": href, "target": "_blank"}})
        elif element.tag in mark_mapping:
            marks.append(mark_mapping[element.tag])

        # Get the text content
        text_content = self._get_element_text(element)
        if not text_content:
            return []

        # Create text node with marks
        text_node: dict[str, Any] = {"type": "text", "text": text_content}
        if marks:
            text_node["marks"] = marks

        return [text_node]

    def _get_element_text(self, element: ET.Element) -> str:
        """Get all text content from an element and its children."""
        text_parts = []

        if element.text:
            text_parts.append(element.text)

        for child in element:
            child_text = self._get_element_text(child)
            if child_text:
                text_parts.append(child_text)
            if child.tail:
                text_parts.append(child.tail)

        return unescape("".join(text_parts))

    def _element_to_markdown(self, element: ET.Element) -> str:
        """Convert an XML element to markdown format."""

        def process_element(elem: ET.Element) -> str:
            text = elem.text or ""

            for child in elem:
                child_text = process_element(child)

                # Convert marks to markdown
                if child.tag in ["strong", "b"]:
                    child_text = f"**{child_text}**"
                elif child.tag in ["em", "i"]:
                    child_text = f"*{child_text}*"
                elif child.tag in ["s", "del"]:
                    child_text = f"~~{child_text}~~"
                elif child.tag == "code":
                    child_text = f"`{child_text}`"
                elif child.tag == "a":
                    href = child.get("href", "")
                    child_text = f"[{child_text}]({href})"

                text += child_text
                if child.tail:
                    text += child.tail

            return text

        return unescape(process_element(element))

    def extract_visualizations_from_notebook_json(self, json_result: list[dict[str, Any]]) -> dict[str, Any]:
        visualizations = {}
        for item in json_result:
            if item["type"] == "ph-query":
                visualizations[item["attrs"]["id"]] = item["attrs"]["query"]
        return visualizations
