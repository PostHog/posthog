from pathlib import Path

import pytest
from unittest.mock import MagicMock

import requests

from posthog.frontend_assets_check import AssetStatus, html_referenced_files, probe_assets


def test_html_referenced_files_reads_every_reference_shape_the_build_writes(tmp_path: Path) -> None:
    (tmp_path / "index.html").write_text(
        "<script>"
        'if (file === "index-LH6WYJJM.js") {}'
        'loadCss(["stylesEagerGlobal-PACX764H.css","stylesEagerApp-XXPG5ZMZ.css"])'
        'fetch("chunk-map-index-1C38A9A1.js")'
        'window.ESBUILD_STATIC_FILES = {"snappy_bg.wasm":"snappy_bg-6B528B99.wasm"}'
        "import('/static/index.js?t=1700000000000')"
        "</script>"
        '<link rel="modulepreload" href="//cdn.example.com/static/Scene-S891A9001EB.js">'
    )
    (tmp_path / "exporter.html").write_text('<script>import("exporter-YECPMJJ7.js")</script>')

    assert html_referenced_files(tmp_path) == {
        "static/Scene-S891A9001EB.js",
        "static/chunk-map-index-1C38A9A1.js",
        "static/exporter-YECPMJJ7.js",
        "static/index-LH6WYJJM.js",
        "static/snappy_bg-6B528B99.wasm",
        "static/stylesEagerApp-XXPG5ZMZ.css",
        "static/stylesEagerGlobal-PACX764H.css",
    }


@pytest.mark.parametrize(
    "outcome, expected",
    [
        (200, AssetStatus.OK),
        (404, AssetStatus.MISSING),
        (403, AssetStatus.UNREACHABLE),
        (502, AssetStatus.UNREACHABLE),
        (requests.ConnectTimeout(), AssetStatus.UNREACHABLE),
        (requests.ConnectionError(), AssetStatus.UNREACHABLE),
    ],
)
def test_probe_assets_counts_only_a_404_as_missing(outcome: int | Exception, expected: AssetStatus) -> None:
    session = MagicMock(spec=requests.Session)
    if isinstance(outcome, Exception):
        session.head.side_effect = outcome
    else:
        response = requests.Response()
        response.status_code = outcome
        session.head.return_value = response

    path = "static/index-LH6WYJJM.js"
    assert probe_assets("https://cdn.example.com", [path], session) == {path: expected}
    session.head.assert_called_once_with(
        "https://cdn.example.com/static/index-LH6WYJJM.js", timeout=5, allow_redirects=True
    )
