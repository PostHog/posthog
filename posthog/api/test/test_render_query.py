from posthog.test.base import APIBaseTest
from unittest.mock import patch

from django.http import HttpResponse


class TestRenderQueryView(APIBaseTest):
    @patch("posthog.api.sharing.get_global_themes", return_value=[{"id": 1}])
    @patch("posthog.views.render_template")
    def test_render_query_page_renders_template(self, mock_render_template, mock_get_global_themes) -> None:
        mock_render_template.return_value = HttpResponse("<html></html>")

        response = self.client.get("/render_query")

        assert response.status_code == 200
        assert "X-Frame-Options" not in response.headers

        mock_render_template.assert_called_once()
        template_name, request = mock_render_template.call_args[0][:2]
        assert template_name == "render_query.html"
        assert request.path == "/render_query"

        mock_get_global_themes.assert_called_once_with()

        context = mock_render_template.call_args.kwargs.get("context")
        assert context == {
            "render_query_payload": {
                "query": None,
                "cachedResults": None,
                "context": None,
                "insight": None,
                "themes": [{"id": 1}],
            }
        }
