import subprocess

import pytest

from posthog.conftest import _sqlx_error_output, run_persons_sqlx_migrations


def test_run_persons_sqlx_migrations_rejects_non_test_database(settings) -> None:
    settings.DATABASES = {
        **settings.DATABASES,
        "default": {**settings.DATABASES["default"], "NAME": "posthog"},
    }

    with pytest.raises(RuntimeError, match="Refusing to run persons migrations against 'posthog_persons'"):
        run_persons_sqlx_migrations()


def test_sqlx_error_output_includes_stdout_and_stderr() -> None:
    error = subprocess.CalledProcessError(1, ["sqlx"], output=b"stdout failure", stderr=b"stderr failure")

    assert _sqlx_error_output(error) == "stdout failure\nstderr failure"
