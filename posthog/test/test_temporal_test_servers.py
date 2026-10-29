from pathlib import Path

import pytest

from posthog.test import temporal_test_servers


@pytest.mark.parametrize(
    ("binaries", "complete"),
    [
        ((), False),
        (("temporal-sdk-python-1.33.0",), False),
        (("temporal-test-server-sdk-python-1.33.0",), False),
        (("temporal-sdk-python-1.33.0", "temporal-test-server-sdk-python-1.33.0"), True),
        (("temporal-sdk-python-1.32.0", "temporal-test-server-sdk-python-1.32.0"), False),
        (("temporal-sdk-python-1.33.0", "temporal-test-server-sdk-python-1.33.0.downloading"), False),
    ],
)
def test_cache_status_requires_both_current_sdk_binaries(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, binaries: tuple[str, ...], complete: bool
) -> None:
    monkeypatch.setattr(temporal_test_servers, "version", lambda _: "1.33.0")
    monkeypatch.setattr(temporal_test_servers, "gettempdir", lambda: str(tmp_path))
    for binary in binaries:
        (tmp_path / binary).touch()
    output_path = tmp_path / "output"
    output_path.write_text("existing=value\n")

    temporal_test_servers.write_cache_status(output_path)

    assert output_path.read_text() == f"existing=value\ncomplete={str(complete).lower()}\n"
