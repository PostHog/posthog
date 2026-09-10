import sys

import pytest

from posthog.middleware import current_rss_mb


@pytest.mark.skipif(sys.platform != "linux", reason="requires /proc (Linux only)")
def test_current_rss_mb_returns_positive_on_linux():
    # On the Linux CI runners /proc/self/statm exists, so this returns the live RSS.
    rss = current_rss_mb()
    # A running Python process always has a non-trivial resident set.
    assert rss is not None
    assert rss > 0


def test_current_rss_mb_handles_missing_proc(monkeypatch):
    # On platforms without /proc (e.g. macOS dev machines) the read fails and we
    # degrade to None rather than raising into the request path.
    def _boom(*_args, **_kwargs):
        raise OSError("no /proc here")

    monkeypatch.setattr("builtins.open", _boom)
    assert current_rss_mb() is None
