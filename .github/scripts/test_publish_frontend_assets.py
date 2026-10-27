import json
from pathlib import Path

import pytest

import publish_frontend_assets as publish


class FakeStore:
    def __init__(self, existing: tuple[str, ...] = (), drop: tuple[str, ...] = ()) -> None:
        self.objects: dict[str, tuple[bytes, str, str]] = dict.fromkeys(existing, (b"", "", ""))
        self.puts: list[str] = []
        self.drop = set(drop)

    def keys(self, prefix: str) -> set[str]:
        return {key for key in self.objects if key.startswith(prefix)}

    def put(self, key: str, body: bytes, content_type: str, cache_control: str) -> None:
        self.puts.append(key)
        if key not in self.drop:
            self.objects[key] = (body, content_type, cache_control)


def write(dist: Path, relative: str) -> None:
    path = dist / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(relative.encode())


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


def test_publish_uploads_new_hashed_files_once_and_fixed_names_always(tmp_path: Path) -> None:
    for relative in (
        "index-AB12CD34.js",
        "chunk-map-index-FFFFFF00.js",
        "assets/snappy_bg-0A1B2C3D.wasm",
        "array.js",
        "toolbar/toolbar-app.css",
    ):
        write(tmp_path, relative)
    store = FakeStore(existing=("static/index-AB12CD34.js", "static/array.js"))

    report = publish.publish(store, publish.scan_build(tmp_path), "abc123", workers=2)

    assert report == publish.PublishReport(uploaded_hashed=2, skipped_hashed=1, uploaded_fixed=2)
    assert "static/index-AB12CD34.js" not in store.puts
    assert store.objects["static/chunk-map-index-FFFFFF00.js"][2] == publish.IMMUTABLE_CACHE
    assert store.objects["static/assets/snappy_bg-0A1B2C3D.wasm"][1] == "application/wasm"
    assert store.objects["static/array.js"][2] == publish.REVALIDATE_CACHE
    assert store.objects["static/toolbar/toolbar-app.css"][1] == "text/css"
    assert set(store.puts[:2]) == {"static/chunk-map-index-FFFFFF00.js", "static/assets/snappy_bg-0A1B2C3D.wasm"}
    assert json.loads(store.objects["builds/abc123.json"][0]) == [
        "static/array.js",
        "static/assets/snappy_bg-0A1B2C3D.wasm",
        "static/chunk-map-index-FFFFFF00.js",
        "static/index-AB12CD34.js",
        "static/toolbar/toolbar-app.css",
    ]


def test_publish_fails_when_a_file_does_not_land(tmp_path: Path) -> None:
    write(tmp_path, "index-AB12CD34.js")
    write(tmp_path, "array.js")
    store = FakeStore(drop=("static/index-AB12CD34.js",))

    with pytest.raises(publish.MissingAfterUpload, match="static/index-AB12CD34.js"):
        publish.publish(store, publish.scan_build(tmp_path), "abc123", workers=1)
