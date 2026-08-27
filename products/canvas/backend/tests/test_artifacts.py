import time
import hashlib

from posthog.test.base import APIBaseTest
from unittest.mock import patch

from posthog.models.scoping import team_scope

from products.canvas.backend import artifacts
from products.canvas.backend.models import Canvas, CanvasBuild, CanvasSourceVersion
from products.tasks.backend.models import Channel

CONTENT = b"<html>hi</html>"


class TestCanvasArtifacts(APIBaseTest):
    def setUp(self):
        super().setUp()
        with team_scope(self.team.id):
            channel = Channel.objects.create(team=self.team, name="general")
            self.canvas = Canvas.objects.create(team=self.team, channel=channel, name="C")
            version = CanvasSourceVersion.objects.create(
                team=self.team,
                canvas=self.canvas,
                source_hash="0" * 64,
                source_object_key="canvas_source/test",
                source_size=1,
            )
            self.content_hash = hashlib.sha256(CONTENT).hexdigest()
            self.build = CanvasBuild.objects.create(
                team=self.team,
                canvas=self.canvas,
                source_version=version,
                status=CanvasBuild.STATUS_READY,
                artifact_object_prefix=f"canvas_artifact/team_{self.team.id}/{self.canvas.id}/x",
                manifest={
                    "entryHtml": "index.html",
                    "assets": [
                        {
                            "path": "index.html",
                            "contentHash": self.content_hash,
                            "sizeBytes": len(CONTENT),
                            "contentType": "text/html; charset=utf-8",
                        }
                    ],
                    "capabilities": {"network": {"origins": ["https://api.example.com"]}},
                },
            )
        reader = patch.object(artifacts.object_storage, "read_bytes", return_value=CONTENT)
        self.read_bytes = reader.start()
        self.addCleanup(reader.stop)

    def _url(self) -> str:
        url = artifacts.create_canvas_artifact_url(self.build, "index.html")
        assert url is not None
        return url.replace("http://localhost:8010", "")

    def test_serves_artifact_with_etag_and_csp(self):
        response = self.client.get(self._url())
        assert response.status_code == 200
        assert response.content == CONTENT
        assert response["ETag"] == f'"{self.content_hash}"'
        assert response["Content-Security-Policy"].startswith("sandbox allow-scripts; default-src 'none'")
        assert "connect-src https://api.example.com" in response["Content-Security-Policy"]
        assert "style-src 'self' 'unsafe-inline' https://api.example.com" in response["Content-Security-Policy"]
        assert "img-src 'self' data: blob: https://api.example.com" in response["Content-Security-Policy"]
        assert "font-src 'self' data: https://api.example.com" in response["Content-Security-Policy"]
        assert "media-src 'self' data: blob: https://api.example.com" in response["Content-Security-Policy"]
        assert "frame-src https://api.example.com" in response["Content-Security-Policy"]
        assert "script-src 'self' https://api.example.com" not in response["Content-Security-Policy"]
        assert response["Cache-Control"] == "private, max-age=31536000, immutable"
        # The sandboxed iframe's opaque origin fetches module scripts in CORS
        # mode; without this the entry bundle is blocked and the canvas
        # white-screens.
        assert response["Access-Control-Allow-Origin"] == "*"

    def test_revalidation_returns_304_without_reading_storage(self):
        url = self._url()
        response = self.client.get(url, HTTP_IF_NONE_MATCH=f'"{self.content_hash}"')
        assert response.status_code == 304
        assert response["Content-Type"] == "text/html; charset=utf-8"
        assert "script-src 'self'" in response["Content-Security-Policy"]
        self.read_bytes.assert_not_called()

    def test_url_is_stable_within_a_bucket(self):
        assert self._url() == self._url()

    def test_expired_bucket_is_rejected(self):
        url = self._url()
        two_buckets = artifacts.ARTIFACT_TOKEN_BUCKET_SECONDS * 2
        with patch.object(artifacts.time, "time", return_value=time.time() + two_buckets):
            response = self.client.get(url)
        assert response.status_code == 404

    def test_unknown_asset_and_unready_build_404(self):
        url = self._url()
        assert self.client.get(url.replace("index.html", "other.js")).status_code == 404

        CanvasBuild.objects.unscoped().filter(id=self.build.id).update(status=CanvasBuild.STATUS_FAILED)
        assert self.client.get(url).status_code == 404

    def test_size_mismatch_404s(self):
        self.read_bytes.return_value = CONTENT + b"tampered"
        assert self.client.get(self._url()).status_code == 404

    def test_content_hash_mismatch_404s(self):
        self.read_bytes.return_value = b"<html>no</html>"
        assert len(self.read_bytes.return_value) == len(CONTENT)
        assert self.client.get(self._url()).status_code == 404

    def test_deleted_canvas_build_404s(self):
        Canvas.objects.unscoped().filter(id=self.canvas.id).update(deleted=True)
        assert self.client.get(self._url()).status_code == 404

    def test_object_storage_source_keys_never_serve(self):
        # The token only addresses manifest assets; a source key is not one.
        url = self._url().replace("index.html", "../../canvas_source/secret")
        assert self.client.get(url).status_code == 404
