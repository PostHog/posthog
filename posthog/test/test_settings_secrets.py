import os
import sys
import subprocess
from pathlib import Path

from posthog.settings.utils import get_from_env, read_secret_file, secret_env


def test_read_secret_file_returns_none_when_dir_unset(monkeypatch):
    monkeypatch.delenv("POSTHOG_SECRETS_DIR", raising=False)
    assert read_secret_file("SECRET_KEY") is None


def test_read_secret_file_returns_none_when_file_missing(monkeypatch, tmp_path):
    monkeypatch.setenv("POSTHOG_SECRETS_DIR", str(tmp_path))
    assert read_secret_file("SECRET_KEY") is None


def test_read_secret_file_returns_exact_contents_no_strip(monkeypatch, tmp_path):
    monkeypatch.setenv("POSTHOG_SECRETS_DIR", str(tmp_path))
    pem = "-----BEGIN PRIVATE KEY-----\nabc\n-----END PRIVATE KEY-----\n"
    (tmp_path / "TEMPORAL_CLIENT_KEY").write_text(pem)
    # No stripping: trailing newline preserved for byte-parity with secretKeyRef env.
    assert read_secret_file("TEMPORAL_CLIENT_KEY") == pem


def test_secret_env_prefers_file_over_env(monkeypatch, tmp_path):
    monkeypatch.setenv("POSTHOG_SECRETS_DIR", str(tmp_path))
    monkeypatch.setenv("SECRET_KEY", "from-env")
    (tmp_path / "SECRET_KEY").write_text("from-file")
    assert secret_env("SECRET_KEY", "default") == "from-file"


def test_secret_env_falls_back_to_env_then_default(monkeypatch, tmp_path):
    monkeypatch.setenv("POSTHOG_SECRETS_DIR", str(tmp_path))
    monkeypatch.delenv("MY_SECRET", raising=False)
    assert secret_env("MY_SECRET", "default") == "default"
    monkeypatch.setenv("MY_SECRET", "from-env")
    assert secret_env("MY_SECRET", "default") == "from-env"


def test_get_from_env_reads_from_file(monkeypatch, tmp_path):
    monkeypatch.setenv("POSTHOG_SECRETS_DIR", str(tmp_path))
    monkeypatch.delenv("CUSTOMER_IO_API_KEY", raising=False)
    (tmp_path / "CUSTOMER_IO_API_KEY").write_text("file-key")
    assert get_from_env("CUSTOMER_IO_API_KEY", "") == "file-key"


def test_get_from_env_file_takes_precedence_over_env(monkeypatch, tmp_path):
    monkeypatch.setenv("POSTHOG_SECRETS_DIR", str(tmp_path))
    monkeypatch.setenv("CUSTOMER_IO_API_KEY", "env-key")
    (tmp_path / "CUSTOMER_IO_API_KEY").write_text("file-key")
    assert get_from_env("CUSTOMER_IO_API_KEY", "") == "file-key"


def _settings_value_in_subprocess(env_extra: dict, expr: str) -> str:
    """Boot Django settings in a clean subprocess and print a settings value.
    Used to prove a migrated setting reads from the secrets dir end-to-end."""
    env = {**os.environ, "DJANGO_SETTINGS_MODULE": "posthog.settings", "TEST": "1", **env_extra}
    code = f"import django; django.setup(); from django.conf import settings; print({expr})"
    return subprocess.check_output([sys.executable, "-c", code], env=env, text=True).strip()


def test_secret_key_loads_from_file(tmp_path):
    (tmp_path / "SECRET_KEY").write_text("secret-from-file")
    out = _settings_value_in_subprocess(
        {"POSTHOG_SECRETS_DIR": str(tmp_path), "SECRET_KEY": "secret-from-env"},
        "settings.SECRET_KEY",
    )
    assert out == "secret-from-file"


def test_encryption_salt_keys_load_from_file(tmp_path):
    (tmp_path / "ENCRYPTION_SALT_KEYS").write_text("00beef0000beef0000beef0000beef00")
    out = _settings_value_in_subprocess(
        {"POSTHOG_SECRETS_DIR": str(tmp_path)},
        "','.join(settings.ENCRYPTION_SALT_KEYS)",
    )
    assert out == "00beef0000beef0000beef0000beef00"


def test_explain_clusters_reads_gemini_from_settings():
    src = Path("ee/hogai/llm_traces_summaries/tools/clustering/explain_clusters.py").read_text()
    assert 'os.getenv("GEMINI_API_KEY")' not in src
    assert "settings.GEMINI_API_KEY" in src


def test_inkeep_provider_reads_key_from_settings():
    src = Path("products/ai_observability/backend/providers/inkeep.py").read_text()
    assert 'os.environ.get("INKEEP_API_KEY")' not in src
    assert "settings.INKEEP_API_KEY" in src
