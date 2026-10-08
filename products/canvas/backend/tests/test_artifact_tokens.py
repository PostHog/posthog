import time
import hashlib

from unittest.mock import MagicMock, patch

from django.core import signing
from django.http import Http404
from django.test import RequestFactory, SimpleTestCase, override_settings

from parameterized import parameterized

from products.canvas.backend.artifacts import (
    ARTIFACT_TOKEN_SALT,
    SANDBOX_DOCUMENT_PATH,
    _parse_sandbox_document,
    _publish_sandbox_document,
    _read_token,
    _sandbox_document,
    canvas_artifact,
    create_canvas_artifact_token,
    create_canvas_artifact_url,
    create_canvas_sandbox_document_url,
)
from products.canvas.backend.checks import check_artifact_delivery_settings


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
    def setUp(self) -> None:
        super().setUp()
        self.write = patch("products.canvas.backend.artifacts.object_storage.write").start()
        self.addCleanup(patch.stopall)
        _publish_sandbox_document.cache_clear()

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
        self.assertEqual(response["Content-Security-Policy"].split(";")[0], "sandbox allow-scripts allow-pointer-lock")
        self.assertIn("connect-src https://api.example.com", response["Content-Security-Policy"])
        self.assertIn("style-src 'self' 'unsafe-inline' https://api.example.com", response["Content-Security-Policy"])
        self.assertIn("img-src 'self' data: blob: https://api.example.com", response["Content-Security-Policy"])
        self.assertIn("frame-src https://api.example.com", response["Content-Security-Policy"])
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

    @override_settings(
        DEBUG=False,
        TEST=False,
        CANVAS_ARTIFACT_ORIGIN="https://usercontent.example",
        CANVAS_ARTIFACT_SIGNING_KEYS=[],
        SECRET_KEY="new-django-signing-key-at-least-32-bytes-long",
        SECRET_KEY_FALLBACKS=["old-django-signing-key-at-least-32-bytes-long"],
    )
    def test_artifact_urls_default_to_rotating_django_signing_keys(self) -> None:
        build = MagicMock(
            team_id=1,
            canvas_id="00000000-0000-0000-0000-000000000001",
            id="00000000-0000-0000-0000-000000000002",
        )

        token = create_canvas_artifact_token(build)

        self.assertIsNotNone(token)
        self.assertEqual(_read_token(token or "")["team_id"], 1)
        previous_token = signing.Signer(
            key="old-django-signing-key-at-least-32-bytes-long", salt=ARTIFACT_TOKEN_SALT
        ).sign_object(_claims(bucket=int(time.time() // 3600)), compress=True)
        self.assertEqual(_read_token(previous_token)["team_id"], 1)

    @override_settings(
        DEBUG=False,
        TEST=False,
        CANVAS_ARTIFACT_ORIGIN="https://usercontent.example",
        CANVAS_ARTIFACT_SIGNING_KEYS=[],
        SECRET_KEY="django-signing-key-at-least-32-bytes-long",
        SECRET_KEY_FALLBACKS=[],
    )
    def test_production_check_accepts_django_signing_key_fallback(self) -> None:
        self.assertEqual(check_artifact_delivery_settings(None), [])

    @override_settings(
        DEBUG=False,
        TEST=False,
        CANVAS_ARTIFACT_ORIGIN="",
        CANVAS_ARTIFACT_SIGNING_KEYS=["dedicated-signing-key-at-least-32-bytes-long"],
    )
    def test_production_check_rejects_a_signing_key_without_an_origin(self) -> None:
        self.assertIn("canvas.E001", [error.id for error in check_artifact_delivery_settings(None)])

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
            self.assertIsNone(create_canvas_sandbox_document_url())
        # A misconfigured origin (non-https, or carrying a path/credentials) is refused.
        with override_settings(CANVAS_ARTIFACT_ORIGIN="http://usercontent.example"):
            self.assertIsNone(create_canvas_artifact_token(MagicMock()))
            self.assertIsNone(create_canvas_sandbox_document_url())
        with override_settings(CANVAS_ARTIFACT_ORIGIN="https://usercontent.example/path"):
            self.assertIsNone(create_canvas_artifact_token(MagicMock()))
            self.assertIsNone(create_canvas_sandbox_document_url())
        self.assertEqual(
            create_canvas_sandbox_document_url(),
            f"https://usercontent.example/canvas-artifacts/sandbox/"
            f"{hashlib.sha256(SANDBOX_DOCUMENT_PATH.read_bytes()).hexdigest()}/index.html",
        )

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


@override_settings(
    CANVAS_ARTIFACT_ORIGIN="https://usercontent.example",
    SITE_URL="https://app.example",
)
class TestCanvasSandboxDocument(SimpleTestCase):
    def setUp(self) -> None:
        super().setUp()
        self.objects: dict[str, bytes] = {}
        writer = patch("products.canvas.backend.artifacts.object_storage.write", side_effect=self.objects.__setitem__)
        reader = patch(
            "products.canvas.backend.artifacts.object_storage.read_bytes",
            side_effect=lambda key, **kwargs: self.objects.get(key),
        )
        writer.start()
        reader.start()
        self.addCleanup(writer.stop)
        self.addCleanup(reader.stop)
        _publish_sandbox_document.cache_clear()
        self.addCleanup(_publish_sandbox_document.cache_clear)

    def test_serves_an_advertised_document_after_the_process_changes_version(self) -> None:
        path = self._path()
        original = _sandbox_document().content
        replacement = _parse_sandbox_document(original + b"\n")
        with patch("products.canvas.backend.artifacts._sandbox_document", return_value=replacement):
            response = self.client.get(path, HTTP_HOST="usercontent.example")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.content, original)

    def _path(self) -> str:
        url = create_canvas_sandbox_document_url()
        assert url is not None
        return url.removeprefix("https://usercontent.example")

    @parameterized.expand([("artifact_host", "usercontent.example", 200), ("app_host", "app.example", 404)])
    def test_serves_only_on_the_artifact_host(self, _name: str, host: str, expected_status: int) -> None:
        response = self.client.get(self._path(), HTTP_HOST=host)

        self.assertEqual(response.status_code, expected_status)

    @parameterized.expand([("generated", False), ("widened_meta_policy", True)])
    def test_serves_the_document_under_its_own_sandboxing_policy(self, _name: str, widen_meta: bool) -> None:
        content = SANDBOX_DOCUMENT_PATH.read_bytes()
        if widen_meta:
            content = content.replace(
                b"default-src 'none';",
                b"sandbox allow-scripts allow-same-origin allow-popups; frame-ancestors *; "
                b"img-src https:; form-action *; base-uri *; default-src 'none';",
            )
        with patch(
            "products.canvas.backend.artifacts._sandbox_document", return_value=_parse_sandbox_document(content)
        ):
            response = self.client.get(self._path(), HTTP_HOST="usercontent.example")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.content, content)
        self.assertEqual(response["Content-Type"], "text/html; charset=utf-8")
        self.assertEqual(response["Cache-Control"], "public, max-age=31536000, immutable")
        self.assertEqual(response["X-Content-Type-Options"], "nosniff")
        self.assertEqual(response["Referrer-Policy"], "no-referrer")
        self.assertNotIn("X-Frame-Options", response)
        self.assertNotIn("Content-Security-Policy-Report-Only", response)
        csp = [part.strip() for part in response["Content-Security-Policy"].split(";")]
        self.assertIn("sandbox allow-scripts", csp)
        self.assertIn("frame-ancestors https://app.example https://posthog.com https://preview.posthog.com", csp)
        self.assertIn("default-src 'none'", csp)
        self.assertTrue(any(part.startswith("script-src ") and "https://esm.sh" in part for part in csp))
        for name, directive in {
            "sandbox": "sandbox allow-scripts",
            "frame-ancestors": "frame-ancestors https://app.example https://posthog.com https://preview.posthog.com",
            "img-src": "img-src data: blob:",
            "form-action": "form-action 'none'",
            "base-uri": "base-uri 'none'",
            "object-src": "object-src 'none'",
        }.items():
            self.assertEqual([part for part in csp if part.split()[0] == name], [directive])

    def test_unknown_content_hash_404s(self) -> None:
        response = self.client.get(f"/canvas-artifacts/sandbox/{'0' * 64}/index.html", HTTP_HOST="usercontent.example")

        self.assertEqual(response.status_code, 404)
