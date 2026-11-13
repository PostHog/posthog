from typing import Any

from posthog.test.base import APIBaseTest
from unittest.mock import ANY, AsyncMock, MagicMock, patch

from parameterized import parameterized

from posthog.models.user import User

from products.exports.backend.facade.api import ExportedAsset

from .trace_fixtures import T0, encode_segment


class TestTraceExportViews(APIBaseTest):
    def setUp(self) -> None:
        super().setUp()
        async_connect = patch("products.exports.backend.facade.api.async_connect", new_callable=AsyncMock)
        self.start_workflow = async_connect.start().return_value.start_workflow
        self.addCleanup(async_connect.stop)

    def _url(self, segment: str, export_id: int | None = None, suffix: str = "") -> str:
        url = f"/api/projects/{self.team.id}/ai_observability/traces/{segment}/exports/"
        return url if export_id is None else f"{url}{export_id}/{suffix}"

    def _create(self, trace_id: str = "a/b") -> dict[str, Any]:
        response = self.client.post(
            self._url(encode_segment(trace_id)), {"timestamp_hint": T0.isoformat()}, format="json"
        )
        assert response.status_code == 201, response.content
        return response.json()

    def test_creates_reports_and_serves_the_export_to_its_creator(self) -> None:
        export = self._create()
        export_id = export["id"]

        assert set(export) == {"id", "status", "filename", "createdAt", "expiresAfter", "exception"}
        assert (export["status"], export["exception"]) == ("pending", None)
        self.start_workflow.assert_awaited_once()
        assert self.client.get(self._url(encode_segment("a/b"), export_id)).json()["status"] == "pending"
        assert self.client.get(self._url(encode_segment("a/b"), export_id, "content/")).status_code == 409

        ExportedAsset.objects.filter(id=export_id).update(content=b'{"trace":{},"nodes":[]}')
        content = self.client.get(self._url(encode_segment("a/b"), export_id, "content/"))

        assert content.status_code == 200
        assert content["Content-Disposition"].startswith("attachment")
        assert self.client.get(f"/api/projects/{self.team.id}/exports/{export_id}/").status_code == 404
        self.assertRedirects(
            self.client.get(f"/api/projects/{self.team.id}/exports/{export_id}/content"),
            self._url(encode_segment("a/b"), export_id, "content"),
            fetch_redirect_response=False,
        )

    @parameterized.expand([("another user", True, "a/b"), ("another trace", False, "c")])
    def test_status_and_content_are_404_for(self, _name: str, as_teammate: bool, url_trace_id: str) -> None:
        export_id = self._create()["id"]
        if as_teammate:
            self.client.force_login(User.objects.create_and_join(self.organization, "peer@example.com", "testtest"))

        for suffix in ("", "content/"):
            assert self.client.get(self._url(encode_segment(url_trace_id), export_id, suffix)).status_code == 404

    def test_an_export_whose_workflow_never_started_fails_at_once(self) -> None:
        self.start_workflow.side_effect = RuntimeError("Temporal is unreachable")

        export = self._create()
        status = self.client.get(self._url(encode_segment("a/b"), export["id"])).json()

        expected = ("failed", "The export could not be started. Try again.")
        assert (export["status"], export["exception"]) == expected
        assert (status["status"], status["exception"]) == expected

    @parameterized.expand([("a download", "", True), ("a copy", "?purpose=copy", False)])
    @patch("products.ai_observability.backend.presentation.views.trace_exports.report_user_action")
    def test_tracks_only_downloads(self, _name: str, query: str, tracked: bool, report_user_action: MagicMock) -> None:
        export_id = self._create()["id"]
        ExportedAsset.objects.filter(id=export_id).update(content=b'{"trace":{},"nodes":[]}')

        with self.captureOnCommitCallbacks(execute=True):
            response = self.client.get(self._url(encode_segment("a/b"), export_id, f"content/{query}"))

        assert (response.status_code, response.content) == (200, b'{"trace":{},"nodes":[]}')
        if tracked:
            report_user_action.assert_called_once_with(
                self.user, "llma trace export downloaded", {"export_id": export_id}, team=self.team, request=ANY
            )
        else:
            report_user_action.assert_not_called()

    def test_rejects_an_unknown_content_purpose(self) -> None:
        export_id = self._create()["id"]

        assert self.client.get(self._url(encode_segment("a/b"), export_id, "content/?purpose=print")).status_code == 400

    def test_a_failed_export_reports_its_reason(self) -> None:
        export_id = self._create()["id"]
        ExportedAsset.objects.filter(id=export_id).update(
            exception="This trace is no longer available.", exception_type="InvalidExportContext"
        )

        status = self.client.get(self._url(encode_segment("a/b"), export_id)).json()
        content = self.client.get(self._url(encode_segment("a/b"), export_id, "content/"))

        assert (status["status"], status["exception"]) == ("failed", "This trace is no longer available.")
        assert (content.status_code, content.json()["detail"]) == (409, "This trace is no longer available.")

    @parameterized.expand(
        [("a malformed hint", encode_segment("a/b"), "yesterday"), ("an unencoded trace id", "a+b", None)]
    )
    def test_rejects(self, _name: str, segment: str, hint: str | None) -> None:
        response = self.client.post(self._url(segment), {"timestamp_hint": hint} if hint else {}, format="json")

        assert response.status_code == 400
        self.start_workflow.assert_not_awaited()

    @patch("posthog.rate_limit.is_rate_limit_enabled", return_value=True)
    @patch(
        "products.ai_observability.backend.presentation.views.trace_exports.TraceExportRateThrottle.rate", new="1/day"
    )
    def test_throttles_exports_per_user(self, _rate_limit: MagicMock) -> None:
        self._create()

        assert self.client.post(self._url(encode_segment("a/b")), {}, format="json").status_code == 429
        self.client.force_login(User.objects.create_and_join(self.organization, "peer@example.com", "testtest"))
        self._create()
