import hashlib

from unittest.mock import MagicMock, patch

from django.core import signing
from django.http import Http404
from django.test import RequestFactory, SimpleTestCase, override_settings

from posthog.api.canvas_artifacts import _read_token, canvas_artifact, create_canvas_artifact_token


class TestCanvasArtifacts(SimpleTestCase):
    @override_settings(CANVAS_ARTIFACT_SIGNING_KEYS=["new-key", "old-key"])
    def test_tokens_rotate_without_invalidating_existing_urls(self) -> None:
        claims = {"team_id": 1, "canvas_id": "canvas", "build_id": "build"}
        token = signing.TimestampSigner(key="old-key", salt="posthog.canvas.artifact.v1").sign_object(
            claims, compress=True
        )

        self.assertEqual(_read_token(token), claims)

    @override_settings(CANVAS_ARTIFACT_SIGNING_KEYS=["key"])
    @patch("posthog.api.canvas_artifacts.object_storage.read_bytes", return_value=b"body")
    @patch("posthog.api.canvas_artifacts.CanvasBuild.objects.for_team")
    def test_only_manifest_listed_files_are_served(self, for_team: MagicMock, read_bytes: MagicMock) -> None:
        build = MagicMock(
            artifact_object_prefix="canvas_artifact/team_1/canvas/build",
            manifest={
                "assets": [
                    {
                        "path": "index.html",
                        "contentType": "text/html; charset=utf-8",
                        "contentHash": hashlib.sha256(b"body").hexdigest(),
                    }
                ]
            },
        )
        for_team.return_value.filter.return_value.first.return_value = build
        token = create_canvas_artifact_token(
            MagicMock(
                team_id=1, canvas_id="00000000-0000-0000-0000-000000000001", id="00000000-0000-0000-0000-000000000002"
            )
        )

        response = canvas_artifact(RequestFactory().get("/"), token or "", "index.html")

        self.assertEqual(response.content, b"body")
        self.assertEqual(response["Content-Disposition"], "inline")
        self.assertEqual(response["X-Content-Type-Options"], "nosniff")
        self.assertEqual(response["Content-Security-Policy"].split(";")[0], "default-src 'none'")
        with self.assertRaises(Http404):
            canvas_artifact(RequestFactory().get("/"), token or "", "source.ts")
        read_bytes.assert_called_once()

    @override_settings(CANVAS_ARTIFACT_SIGNING_KEYS=["key"])
    @patch("posthog.api.canvas_artifacts.object_storage.read_bytes", return_value=b"tampered")
    @patch("posthog.api.canvas_artifacts.CanvasBuild.objects.for_team")
    def test_corrupt_stored_artifact_is_not_served(self, for_team: MagicMock, _read_bytes: MagicMock) -> None:
        for_team.return_value.filter.return_value.first.return_value = MagicMock(
            artifact_object_prefix="canvas_artifact/team_1/canvas/build",
            manifest={"assets": [{"path": "index.html", "contentHash": hashlib.sha256(b"safe").hexdigest()}]},
        )
        token = create_canvas_artifact_token(
            MagicMock(
                team_id=1, canvas_id="00000000-0000-0000-0000-000000000001", id="00000000-0000-0000-0000-000000000002"
            )
        )

        with self.assertRaises(Http404):
            canvas_artifact(RequestFactory().get("/"), token or "", "index.html")

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
