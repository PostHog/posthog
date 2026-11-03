from datetime import UTC, datetime, timedelta

from django.test import override_settings

from parameterized import parameterized

from posthog.jwt import PosthogJwtAudience, decode_jwt
from posthog.session_recordings.recordings.replay_blocks_jwt import mint_replay_blocks_token


class TestMintReplayBlocksToken:
    @parameterized.expand(
        [
            ("no_limit", None, 60 * 60),
            ("share_ends_in_ten_minutes", timedelta(minutes=10), 10 * 60),
            ("share_ends_after_the_ttl", timedelta(hours=3), 60 * 60),
        ]
    )
    @override_settings(RECORDING_API_BLOCKS_JWT_SECRET="blocks-key")
    def test_token_never_outlives_the_access_behind_it(
        self, _name: str, access_left: timedelta | None, expected_seconds: int
    ) -> None:
        now = datetime.now(tz=UTC)
        minted = mint_replay_blocks_token(
            2, "session", "s1", "browser", not_after=now + access_left if access_left else None
        )

        assert minted is not None
        claims = decode_jwt(minted.token, PosthogJwtAudience.REPLAY_BLOCKS, verification_keys=["blocks-key"])
        assert abs(claims["exp"] - claims["iat"] - expected_seconds) <= 1
        assert abs(minted.expires_at.timestamp() - claims["exp"]) <= 1

    @override_settings(RECORDING_API_BLOCKS_JWT_SECRET="blocks-key")
    def test_no_token_once_the_access_has_ended(self) -> None:
        assert mint_replay_blocks_token(2, "session", "s1", "browser", not_after=datetime.now(tz=UTC)) is None
