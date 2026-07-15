from django.test import SimpleTestCase

from parameterized import parameterized

from products.conversations.backend.services.attachments import build_content_with_images, sanitize_attachment_filename


class TestAttachmentsService(SimpleTestCase):
    def test_build_content_renders_files_as_links(self) -> None:
        files = [{"url": "https://app.posthog.com/uploaded_media/a", "name": "invoice.pdf"}]
        content, rich_content = build_content_with_images("hello", None, [], files)

        assert "[invoice.pdf](https://app.posthog.com/uploaded_media/a)" in content
        assert rich_content is not None
        link_nodes = [
            n
            for n in rich_content["content"]
            if n["type"] == "paragraph"
            and any(m["type"] == "link" for c in n.get("content", []) for m in c.get("marks", []))
        ]
        assert len(link_nodes) == 1

    def test_build_content_renders_images_and_files_together(self) -> None:
        images = [{"url": "https://app.posthog.com/uploaded_media/img", "name": "shot.png"}]
        files = [{"url": "https://app.posthog.com/uploaded_media/doc", "name": "doc.pdf"}]
        content, rich_content = build_content_with_images("", None, images, files)

        assert "![shot.png](https://app.posthog.com/uploaded_media/img)" in content
        assert "[doc.pdf](https://app.posthog.com/uploaded_media/doc)" in content
        assert rich_content is not None
        node_types = [n["type"] for n in rich_content["content"]]
        assert "image" in node_types
        assert "paragraph" in node_types

    def test_build_content_no_attachments_returns_unchanged(self) -> None:
        content, rich_content = build_content_with_images("just text", None, [], [])
        assert content == "just text"
        assert rich_content is None

    @parameterized.expand(
        [
            ("markdown_link", "evil](https://phish.example.com).pdf", ["[", "]"]),
            ("markdown_image", "![x](y).png", ["[", "]", "!"]),
            ("path_traversal", "../../etc/passwd", ["/"]),
        ]
    )
    def test_sanitize_strips_dangerous_chars(self, _label: str, raw: str, forbidden: list[str]) -> None:
        cleaned = sanitize_attachment_filename(raw)
        for ch in forbidden:
            assert ch not in cleaned

    def test_sanitize_empty_falls_back(self) -> None:
        assert sanitize_attachment_filename(None) == "attachment"
        assert sanitize_attachment_filename("   ") == "attachment"
