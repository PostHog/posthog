from datetime import UTC, datetime

from django.test import override_settings

from posthog.jwt import PosthogJwtAudience, decode_jwt
from posthog.session_recordings.recordings.replay_proxy_jwt import mint_replay_proxy_token


class TestMintReplayProxyToken:
    @override_settings(REPLAY_PROXY_JWT_SECRET="primary-key,old-key", CLOUD_DEPLOYMENT="EU")
    def test_mints_team_scoped_token_the_proxy_accepts(self):
        before = datetime.now(tz=UTC)
        token = mint_replay_proxy_token(123)

        assert token is not None
        decoded = decode_jwt(token, PosthogJwtAudience.REPLAY_PROXY, verification_keys=["primary-key"])
        assert decoded["aud"] == "posthog:replay_proxy"
        assert decoded["team_id"] == 123
        assert decoded["region"] == "EU"
        assert 59 * 60 < decoded["exp"] - before.timestamp() < 61 * 60

    @override_settings(REPLAY_PROXY_JWT_SECRET="")
    def test_returns_none_without_a_secret(self):
        assert mint_replay_proxy_token(123) is None
