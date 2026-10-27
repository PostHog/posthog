import json
from pathlib import Path

import pytest

import publish_frontend_assets as publish


class FakeStore:
    def __init__(self, existing: dict[str, bytes]) -> None:
        self.objects: dict[str, tuple[bytes, str, str]] = {key: (body, "", "") for key, body in existing.items()}
        self.puts: list[str] = []

    def etag(self, key: str) -> str | None:
        return publish.content_md5(self.objects[key][0]) if key in self.objects else None

    def put(self, key: str, body: bytes, content_type: str, cache_control: str) -> None:
        self.puts.append(key)
        self.objects[key] = (body, content_type, cache_control)


@pytest.mark.parametrize(
    "name,hashed",
    [
        ("chunk-map-index-AB12CD34.js", True),
        ("sql_more-ABCDEF.js", True),
        ("Inter-ABCDEF12.woff2", True),
        ("array.js", False),
        ("array.full.es5.js", False),
        ("toolbar-app.css", False),
        ("exception-autocapture.js", False),
        ("index.html", False),
        ("chunk-abcdef12.js", False),
    ],
)
def test_hashed_file_name(name: str, hashed: bool) -> None:
    assert bool(publish.HASHED_FILE.match(name)) is hashed


def test_publish_uploads_changed_files_and_skips_matching_ones(tmp_path: Path) -> None:
    for relative in (
        "index-AB12CD34.js",
        "index-AB12CD34.js.map",
        "chunk-map-index-FFFFFF00.js",
        "assets/snappy_bg-0A1B2C3D.wasm",
        "array.js",
        "toolbar/toolbar-app.css",
    ):
        path = tmp_path / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(relative.encode())
    store = FakeStore(
        existing={
            "static/index-AB12CD34.js": b"index-AB12CD34.js",
            "static/chunk-map-index-FFFFFF00.js": b"older release id",
            "static/array.js": b"array.js",
        }
    )

    report = publish.publish(store, publish.scan_build(tmp_path), "abc123", workers=2)

    assert report == publish.PublishReport(uploaded=3, unchanged=2)
    assert "static/index-AB12CD34.js" not in store.puts
    assert "static/array.js" not in store.puts
    assert "static/index-AB12CD34.js.map" not in store.objects
    assert store.objects["static/chunk-map-index-FFFFFF00.js"] == (
        b"chunk-map-index-FFFFFF00.js",
        "text/javascript",
        publish.IMMUTABLE_CACHE,
    )
    assert store.objects["static/assets/snappy_bg-0A1B2C3D.wasm"][1] == "application/wasm"
    assert store.objects["static/toolbar/toolbar-app.css"][1:] == ("text/css", publish.REVALIDATE_CACHE)
    assert set(store.puts[:2]) == {"static/chunk-map-index-FFFFFF00.js", "static/assets/snappy_bg-0A1B2C3D.wasm"}
    assert json.loads(store.objects["builds/abc123.json"][0]) == [
        "static/array.js",
        "static/assets/snappy_bg-0A1B2C3D.wasm",
        "static/chunk-map-index-FFFFFF00.js",
        "static/index-AB12CD34.js",
        "static/toolbar/toolbar-app.css",
    ]
