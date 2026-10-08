import json
from uuid import UUID

from unittest.mock import patch

from django.template import Context, Template
from django.test import SimpleTestCase, TestCase

from posthog.templatetags.posthog_filters import compact_number


class TestTemplateTags(TestCase):
    def test_compact_number(self):
        self.assertEqual(compact_number(5001), "5K")
        self.assertEqual(compact_number(5312), "5.31K")
        self.assertEqual(compact_number(5392), "5.39K")
        self.assertEqual(compact_number(2833102), "2.83M")
        self.assertEqual(compact_number(8283310234), "8.28B")


class TestPageJsonScript(SimpleTestCase):
    @patch("posthog.templatetags.posthog_filters.capture_exception")
    def test_unserializable_value_renders_null_and_is_reported(self, mock_capture) -> None:
        uuid = UUID("00000000-0000-4000-8000-000000000001")
        html = Template('{{ value|page_json_script:"x" }}').render(Context({"value": {"bad": {1}, "id": uuid}}))

        body = html.split(">", 1)[1].rsplit("</script>", 1)[0]
        self.assertEqual(json.loads(body), {"bad": None, "id": str(uuid)})
        mock_capture.assert_called_once()
        self.assertIn("set", str(mock_capture.call_args.args[0]))
