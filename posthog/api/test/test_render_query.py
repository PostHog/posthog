from posthog.test.base import APIBaseTest
from unittest.mock import patch

from django.http import HttpResponse


class TestRenderQueryView(APIBaseTest):
    @patch("posthog.views.render_template")
    def test_render_query_page_renders_template(self, mock_render_template) -> None:
        mock_render_template.return_value = HttpResponse("<html></html>")

        response = self.client.get("/render_query")

        assert response.status_code == 200
        assert "X-Frame-Options" not in response.headers

        mock_render_template.assert_called_once()
        template_name, request = mock_render_template.call_args[0][:2]
        assert template_name == "render_query.html"
        assert request.path == "/render_query"

        context = mock_render_template.call_args.kwargs.get("context")
        assert context == {
            "render_query_payload": {
                "query": None,
                "cachedResults": None,
                "context": None,
                "insight": None,
            }
        }
