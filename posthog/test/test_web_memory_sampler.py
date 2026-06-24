import threading

import posthog.web_memory_sampler as sampler


def test_current_rss_mb_returns_positive_on_linux():
    rss = sampler.current_rss_mb()
    assert rss is not None
    assert rss > 0


def test_current_rss_mb_handles_missing_proc(monkeypatch):
    def _boom(*_args, **_kwargs):
        raise OSError("no /proc here")

    monkeypatch.setattr("builtins.open", _boom)
    assert sampler.current_rss_mb() is None


def test_sampler_disabled_starts_no_thread(monkeypatch):
    # A non-positive interval must be a no-op so the sampler can be turned off in prod
    # without a deploy, and so it never spawns a thread in environments that don't want it.
    monkeypatch.setattr(sampler, "_sampler_started", False)
    monkeypatch.setenv("WEB_MEMORY_SAMPLE_INTERVAL_SECONDS", "0")

    sampler.start_web_memory_sampler()

    assert sampler._sampler_started is False
    assert not any(t.name == "web-memory-sampler" for t in threading.enumerate())
