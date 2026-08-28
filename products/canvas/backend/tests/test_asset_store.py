from io import BytesIO

from django.test import SimpleTestCase

from parameterized import parameterized
from PIL import Image, features

from products.canvas.backend.asset_store import sniff_image_content_type

VALID_SVG = b'<svg xmlns="http://www.w3.org/2000/svg" width="1" height="1"></svg>'


class TestSniffImageContentType(SimpleTestCase):
    def test_accepts_a_well_formed_svg(self):
        assert sniff_image_content_type(VALID_SVG) == "image/svg+xml"

    @parameterized.expand(
        [
            ("bare_prefix", b"<svg"),
            ("unclosed_fragment", b"<svg unclosed <<< &nope; not xml"),
            ("html_document_embedding_svg", b"<!DOCTYPE html><html><body><svg></svg></body></html>"),
            ("text_mentioning_svg", b"a note about <svg elements"),
            (
                "entity_definition",
                b'<?xml version="1.0"?><!DOCTYPE svg [<!ENTITY x "y">]>'
                b'<svg xmlns="http://www.w3.org/2000/svg">&x;</svg>',
            ),
        ]
    )
    def test_rejects_malformed_or_non_svg(self, _name, data):
        assert sniff_image_content_type(data) is None

    def test_avif_is_decoded_not_trusted_by_signature(self):
        if not features.check("avif"):
            self.skipTest("Pillow build has no AVIF support; the sniffer falls back to the signature")
        buffer = BytesIO()
        Image.new("RGB", (2, 2), (255, 0, 0)).save(buffer, format="AVIF")
        assert sniff_image_content_type(buffer.getvalue()) == "image/avif"
        # Carries the ftyp signature but is not a decodable AVIF.
        assert sniff_image_content_type(b"\x00\x00\x00\x18ftypavif" + b"\x00" * 32) is None
