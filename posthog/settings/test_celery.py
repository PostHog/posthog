import importlib
from collections.abc import Iterator
from types import ModuleType
from typing import Optional

import pytest

from celery import Celery
from redbeat.schedulers import RedBeatConfig

# Import by path: `posthog.settings` re-exports the celery library under the name `celery`, which
# shadows this submodule.
celery_settings = importlib.import_module("posthog.settings.celery")


@pytest.fixture
def clean_env(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    for name in ("REDBEAT_LOCK_KEY", "REDBEAT_LOCK_TIMEOUT", "CELERY_BEAT_MAX_LOOP_INTERVAL"):
        monkeypatch.delenv(name, raising=False)
    yield
    monkeypatch.undo()
    importlib.reload(celery_settings)


def _reload() -> ModuleType:
    return importlib.reload(celery_settings)


def _redbeat_lock_key(lock_key: Optional[str]) -> Optional[str]:
    app = Celery("test")
    app.conf.broker_url = "redis://localhost:6379"
    app.conf.REDBEAT_LOCK_KEY = lock_key
    return RedBeatConfig(app).lock_key


@pytest.mark.parametrize(
    "env_value,expected",
    [(None, "redbeat::lock"), ("", None), ("redbeat:custom", "redbeat:custom")],
)
def test_redbeat_lock_key_reads_the_environment(
    clean_env: None, monkeypatch: pytest.MonkeyPatch, env_value: Optional[str], expected: Optional[str]
) -> None:
    if env_value is not None:
        monkeypatch.setenv("REDBEAT_LOCK_KEY", env_value)

    lock_key = _reload().REDBEAT_LOCK_KEY

    assert lock_key == expected
    assert _redbeat_lock_key(lock_key) == expected


def test_beat_intervals_read_the_environment_as_integers(clean_env: None, monkeypatch: pytest.MonkeyPatch) -> None:
    defaults = _reload()
    assert defaults.REDBEAT_LOCK_TIMEOUT == 45
    assert defaults.CELERY_BEAT_MAX_LOOP_INTERVAL == 30

    monkeypatch.setenv("REDBEAT_LOCK_TIMEOUT", "300")
    monkeypatch.setenv("CELERY_BEAT_MAX_LOOP_INTERVAL", "60")
    reloaded = _reload()

    assert reloaded.REDBEAT_LOCK_TIMEOUT == 300
    assert reloaded.CELERY_BEAT_MAX_LOOP_INTERVAL == 60
