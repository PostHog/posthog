import time
import hashlib

from unittest.mock import MagicMock, patch

from django.core import signing
from django.http import Http404
from django.test import RequestFactory, SimpleTestCase, override_settings

from products.canvas.backend.artifacts import (
    ARTIFACT_TOKEN_SALT,
    _read_token,
    canvas_artifact,
    create_canvas_artifact_token,
    create_canvas_artifact_url,
)


def _claims(**overrides):
    # _read_token only accepts a token whose bucket is the current or previous
    # one, so mint through the real code path rather than hard-coding a bucket.
    return {
        "team_id": 1,
        "canvas_id": "00000000-0000-0000-0000-000000000001",
        "build_id": "00000000-0000-0000-0000-000000000002",
        **overrides,
    }


class TestCanvasArtifactTokens(SimpleTestCase):
    @override_settings(
        CANVAS_ARTIFACT_SIGNING_KEYS=["new-key-at-least-32-bytes-long", "old-key-at-least-32-bytes-long"]
    )
    def test_tokens_rotate_without_invalidating_existing_urls(self) -> None:
        # A token signed under a retired key still verifies while that key is in
        # the list; new tokens are minted under the first key.
        bucket = int(time.time() // 3600)
        claims = _claims(bucket=bucket)
        old_token = signing.Signer(key="old-key-at-least-32-bytes-long", salt=ARTIFACT_TOKEN_SALT).sign_object(
            claims, compress=True
        )

        self.assertEqual(_read_token(old_token), claims)

    @override_settings(CANVAS_ARTIFACT_SIGNING_KEYS=["key"])
    @patch("products.canvas.backend.artifacts.object_storage.read_bytes", return_value=b"body")
    @patch("products.canvas.backend.artifacts.CanvasBuild")
    def test_only_manifest_listed_files_are_served(self, canvas_build: MagicMock, read_bytes: MagicMock) -> None:
        content = b"body"
        build = MagicMock(
            artifact_object_prefix="canvas_artifact/team_1/canvas/build",
            manifest={
                "capabilities": {
                    # The second origin smuggles a CSP delimiter but no wildcard, so it
                    # slips past every gate except the hostname charset check. Rendering
                    # it verbatim would inject an attacker-chosen img-src directive.
                    "network": {"origins": ["https://api.example.com", "https://example.com; img-src evil.example.net"]}
                },
                "assets": [
                    {
                        "path": "index.html",
                        "contentType": "text/html; charset=utf-8",
                        "contentHash": hashlib.sha256(content).hexdigest(),
                        "sizeBytes": len(content),
                    }
                ],
            },
        )
        canvas_build.objects.for_team.return_value.filter.return_value.first.return_value = build
        token = create_canvas_artifact_token(
            MagicMock(
                team_id=1, canvas_id="00000000-0000-0000-0000-000000000001", id="00000000-0000-0000-0000-000000000002"
            )
        )

        response = canvas_artifact(RequestFactory().get("/"), token or "", "index.html")

        self.assertEqual(response.content, content)
        self.assertEqual(response["Content-Disposition"], "inline")
        self.assertEqual(response["X-Content-Type-Options"], "nosniff")
        self.assertEqual(response["Content-Security-Policy"].split(";")[0], "sandbox allow-scripts")
        self.assertIn("connect-src https://api.example.com", response["Content-Security-Policy"])
        self.assertNotIn("evil.example.net", response["Content-Security-Policy"])
        with self.assertRaises(Http404):
            canvas_artifact(RequestFactory().get("/"), token or "", "source.ts")
        read_bytes.assert_called_once()

    @override_settings(CANVAS_ARTIFACT_SIGNING_KEYS=["key"])
    @patch("products.canvas.backend.artifacts.object_storage.read_bytes", return_value=b"tampered")
    @patch("products.canvas.backend.artifacts.CanvasBuild")
    def test_corrupt_stored_artifact_is_not_served(self, canvas_build: MagicMock, _read_bytes: MagicMock) -> None:
        canvas_build.objects.for_team.return_value.filter.return_value.first.return_value = MagicMock(
            artifact_object_prefix="canvas_artifact/team_1/canvas/build",
            manifest={
                "assets": [
                    {
                        "path": "index.html",
                        "contentHash": hashlib.sha256(b"safe").hexdigest(),
                        "sizeBytes": len(b"safe"),
                    }
                ]
            },
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

    @override_settings(
        DEBUG=True,
        TEST=False,
        CANVAS_ARTIFACT_SIGNING_KEYS=["a-development-signing-key-at-least-32-bytes"],
        CANVAS_ARTIFACT_ORIGIN="https://usercontent.example",
    )
    def test_configured_origin_is_enforced_in_debug(self) -> None:
        build = MagicMock(team_id=1, canvas_id="canvas", id="build")
        token = create_canvas_artifact_token(build)

        with self.assertRaises(Http404):
            canvas_artifact(RequestFactory().get("/", HTTP_HOST="app.example"), token or "", "index.html")

    @override_settings(
        DEBUG=False,
        TEST=False,
        CANVAS_ARTIFACT_SIGNING_KEYS=["a-production-signing-key-at-least-32-bytes"],
        CANVAS_ARTIFACT_ORIGIN="https://usercontent.example",
    )
    def test_production_token_requires_a_valid_origin_and_key(self) -> None:
        # A too-short primary key is refused in production (fail closed).
        with override_settings(CANVAS_ARTIFACT_SIGNING_KEYS=["too-short"]):
            self.assertIsNone(create_canvas_artifact_token(MagicMock()))
        # A misconfigured origin (non-https, or carrying a path/credentials) is refused.
        with override_settings(CANVAS_ARTIFACT_ORIGIN="http://usercontent.example"):
            self.assertIsNone(create_canvas_artifact_token(MagicMock()))
        with override_settings(CANVAS_ARTIFACT_ORIGIN="https://usercontent.example/path"):
            self.assertIsNone(create_canvas_artifact_token(MagicMock()))

    @override_settings(CANVAS_ARTIFACT_SIGNING_KEYS=["a-signing-key-at-least-32-bytes-long"])
    def test_url_round_trips_through_read_token(self) -> None:
        build = MagicMock(
            team_id=1, canvas_id="00000000-0000-0000-0000-000000000001", id="00000000-0000-0000-0000-000000000002"
        )
        url = create_canvas_artifact_url(build, "index.html")
        self.assertIsNotNone(url)
        token = (url or "").split("/canvas-artifacts/")[1].split("/")[0]
        claims = _read_token(token)
        self.assertEqual(claims["team_id"], 1)
        self.assertEqual(claims["canvas_id"], "00000000-0000-0000-0000-000000000001")
