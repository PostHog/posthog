import pytest

from posthog.clickhouse.client.connection import ClickHouseCredentials
from posthog.dags.common.resources import _dedicated_user_connection_overrides


@pytest.mark.parametrize("file_backed", [True, False], ids=["file_backed_uses_the_token", "static_keeps_its_password"])
def test_dedicated_user_connection_overrides(tmp_path, file_backed) -> None:
    token_file = tmp_path / "token"
    token_file.write_text("live-token")
    creds = ClickHouseCredentials(
        user="backups",
        password="static-password",
        password_file=str(token_file) if file_backed else None,
    )

    overrides = _dedicated_user_connection_overrides(creds)

    assert overrides["user"] == "backups"
    if file_backed:
        assert "password" not in overrides
        assert overrides["credential_provider"]() == "live-token"
    else:
        assert "credential_provider" not in overrides
        assert overrides["password"] == "static-password"
