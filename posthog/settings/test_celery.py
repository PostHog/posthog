import os
import importlib
from collections.abc import Iterator

import pytest
from unittest import mock

from posthog.settings.data_stores import REDIS_URL

# The settings package re-exports the celery package under this name, so import the module by path.
celery_settings = importlib.import_module("posthog.settings.celery")


@pytest.mark.parametrize(
    "url,expected",
    [
        ("rediss://broker:6379", "rediss://broker:6379?ssl_cert_reqs=required"),
        ("rediss://broker:6379/0?socket_timeout=5", "rediss://broker:6379/0?socket_timeout=5&ssl_cert_reqs=required"),
        ("rediss://broker:6379?ssl_cert_reqs=none", "rediss://broker:6379?ssl_cert_reqs=none"),
        ("redis://broker:6379", "redis://broker:6379"),
        (None, None),
    ],
)
def test_with_tls_verification(url: str | None, expected: str | None) -> None:
    assert celery_settings.with_tls_verification(url) == expected


@pytest.fixture
def reload_celery_settings() -> Iterator[None]:
    yield
    importlib.reload(celery_settings)


@pytest.mark.parametrize(
    "env,expected",
    [
        (
            {},
            {
                "CELERY_BROKER_URL": REDIS_URL,
                "CELERY_BROKER_READ_URL": None,
                "CELERY_BROKER_WRITE_URL": None,
                "CELERY_RESULT_BACKEND": REDIS_URL,
                "CELERY_REDBEAT_REDIS_URL": REDIS_URL,
            },
        ),
        (
            {"CELERY_BROKER_REDIS_URL": "rediss://broker:6379"},
            {
                "CELERY_BROKER_URL": "rediss://broker:6379?ssl_cert_reqs=required",
                "CELERY_RESULT_BACKEND": REDIS_URL,
                "CELERY_REDBEAT_REDIS_URL": REDIS_URL,
            },
        ),
        (
            {"CELERY_BROKER_READ_REDIS_URL": "redis://old:6379", "CELERY_BROKER_WRITE_REDIS_URL": "rediss://new:6379"},
            {
                "CELERY_BROKER_URL": REDIS_URL,
                "CELERY_BROKER_READ_URL": "redis://old:6379",
                "CELERY_BROKER_WRITE_URL": "rediss://new:6379?ssl_cert_reqs=required",
            },
        ),
    ],
)
@pytest.mark.usefixtures("reload_celery_settings")
def test_celery_redis_urls(env: dict[str, str], expected: dict[str, str | None]) -> None:
    with mock.patch.dict(os.environ, env):
        importlib.reload(celery_settings)

    assert {name: getattr(celery_settings, name) for name in expected} == expected


@pytest.mark.parametrize(
    "env,expected",
    [
        ({}, None),
        ({"CELERY_BROKER_VISIBILITY_TIMEOUT_SECONDS": "43200"}, {"visibility_timeout": 43200}),
    ],
)
@pytest.mark.usefixtures("reload_celery_settings")
def test_broker_visibility_timeout(env: dict[str, str], expected: dict[str, int] | None) -> None:
    with mock.patch.dict(os.environ, env):
        importlib.reload(celery_settings)

    assert getattr(celery_settings, "CELERY_BROKER_TRANSPORT_OPTIONS", None) == expected
