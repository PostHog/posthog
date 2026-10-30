from django.test import SimpleTestCase

from parameterized import parameterized

from products.conversations.backend.services.email_html import html_to_text, looks_like_html_document


class TestEmailHtml(SimpleTestCase):
    def test_many_sibling_paragraphs_flatten_in_one_pass(self) -> None:
        assert html_to_text("<p>x</p>" * 20_000) == "\n\n".join(["x"] * 20_000)

    @parameterized.expand(
        [
            ("doctype", "<!DOCTYPE html>\n<html><body><p>Hi</p></body></html>", True),
            ("html_tag_with_attributes", '<html lang="en"><body>Hi</body></html>', True),
            ("xml_declaration_first", '<?xml version="1.0"?><!DOCTYPE html><html>Hi</html>', True),
            # A customer who pastes markup to ask about it must keep it.
            ("prose_that_quotes_markup", 'This breaks for me:\n<div id="app"></div>\nAny ideas?', False),
            ("document_pasted_under_prose", "Here is my page:\n<!DOCTYPE html><html></html>", False),
        ]
    )
    def test_document_detection(self, _name: str, text: str, expected: bool) -> None:
        assert looks_like_html_document(text) is expected
