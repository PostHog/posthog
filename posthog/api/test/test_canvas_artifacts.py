from unittest.mock import MagicMock, patch

from django.core import signing
from django.http import Http404
from django.test import RequestFactory, SimpleTestCase, override_settings

from posthog.api.canvas_artifacts import _read_token, canvas_artifact, create_canvas_artifact_token


class TestCanvasArtifacts(SimpleTestCase):
    @override_settings(CANVAS_ARTIFACT_SIGNING_KEYS=["new-key", "old-key"])
    def test_tokens_rotate_without_invalidating_existing_urls(self) -> None:
        claims = {"team_id": 1, "canvas_id": "canvas", "build_id": "build"}
        old_token = signing.TimestampSigner(key="old-key", salt="posthog.canvas.artifact.v1").sign_object(
            claims, compress=True
        )

        self.assertEqual(_read_token(old_token), claims)

    @override_settings(CANVAS_ARTIFACT_SIGNING_KEYS=["key"])
    @patch("django.core.signing.time.time", side_effect=[1000, 1301])
    def test_tokens_expire_after_five_minutes(self, _time: MagicMock) -> None:
        build = MagicMock(team_id=1, canvas_id="canvas", id="build")
        token = create_canvas_artifact_token(build)

        self.assertIsNotNone(token)
        with self.assertRaises(Http404):
            _read_token(token or "")

    @override_settings(CANVAS_ARTIFACT_SIGNING_KEYS=["key"])
    @patch("posthog.api.canvas_artifacts.object_storage.read_bytes", return_value=b"body")
    @patch("posthog.api.canvas_artifacts.CanvasBuild.objects.for_team")
    def test_only_manifest_listed_files_are_served(self, for_team: MagicMock, read_bytes: MagicMock) -> None:
        build = MagicMock(
            team_id=1,
            canvas_id="00000000-0000-0000-0000-000000000001",
            id="00000000-0000-0000-0000-000000000002",
            artifact_object_prefix="canvas/artifacts/1/00000000-0000-0000-0000-000000000002",
            manifest={
                "files": [
                    {
                        "path": "index.html",
                        "contentType": "text/html; charset=utf-8",
                        "bytes": 4,
                        "sha256": "0" * 64,
                    }
                ]
            },
        )
        for_team.return_value.filter.return_value.first.return_value = build
        token = create_canvas_artifact_token(build)
        request = RequestFactory().get("/")

        response = canvas_artifact(request, token or "", "index.html")

        self.assertEqual(response.content, b"body")
        self.assertTrue(response.xframe_options_exempt)
        self.assertEqual(response["Content-Disposition"], "inline")
        self.assertEqual(response["X-Content-Type-Options"], "nosniff")
        read_bytes.assert_called_once_with("canvas/artifacts/1/00000000-0000-0000-0000-000000000002/index.html")

        with self.assertRaises(Http404):
            canvas_artifact(request, token or "", "source.ts")
        read_bytes.assert_called_once()

    @override_settings(CANVAS_ARTIFACT_SIGNING_KEYS=[])
    def test_artifact_urls_fail_closed_without_signing_keys(self) -> None:
        self.assertIsNone(create_canvas_artifact_token(MagicMock()))

    @override_settings(
        DEBUG=False,
        TEST=False,
        CANVAS_ARTIFACT_SIGNING_KEYS=["a-production-signing-key-at-least-32-bytes"],
        CANVAS_ARTIFACT_ORIGIN="https://usercontent.example",
    )
    def test_production_artifacts_are_not_served_from_the_application_origin(self) -> None:
        build = MagicMock(team_id=1, canvas_id="canvas", id="build")
        token = create_canvas_artifact_token(build)

        with self.assertRaises(Http404):
            canvas_artifact(RequestFactory().get("/", HTTP_HOST="app.example"), token or "", "index.html")

    @override_settings(
        DEBUG=False,
        TEST=False,
        CANVAS_ARTIFACT_SIGNING_KEYS=["a-production-signing-key-at-least-32-bytes"],
        CANVAS_ARTIFACT_ORIGIN="",
    )
    def test_production_token_generation_requires_a_dedicated_origin(self) -> None:
        self.assertIsNone(create_canvas_artifact_token(MagicMock()))

    @override_settings(
        DEBUG=False,
        TEST=False,
        CANVAS_ARTIFACT_SIGNING_KEYS=["short"],
        CANVAS_ARTIFACT_ORIGIN="https://usercontent.example",
    )
    def test_production_token_generation_requires_a_strong_signing_key(self) -> None:
        self.assertIsNone(create_canvas_artifact_token(MagicMock()))
