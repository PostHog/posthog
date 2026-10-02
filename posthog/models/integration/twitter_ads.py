import hashlib
from typing import TYPE_CHECKING
from urllib.parse import parse_qs, urlencode

from django.conf import settings
from django.core.cache import cache
from django.utils.http import url_has_allowed_host_and_scheme

import requests
from requests_oauthlib import OAuth1
from rest_framework.exceptions import ValidationError

from posthog.models.integration.model import Integration
from posthog.models.integration.oauth import OauthIntegration

if TYPE_CHECKING:
    from posthog.models.user import User


class TwitterAdsIntegration:
    binding_ttl = 600

    @staticmethod
    def binding_key(token: str) -> str:
        return f"twitter_ads_oauth:{hashlib.sha256(token.encode()).hexdigest()}"

    @staticmethod
    def require_configured() -> None:
        if not settings.TWITTER_ADS_CONSUMER_KEY or not settings.TWITTER_ADS_CONSUMER_SECRET:
            raise ValidationError("Kind not configured")

    @staticmethod
    def _exchange(endpoint: str, auth: OAuth1, required: tuple[str, ...]) -> dict[str, str]:
        try:
            response = requests.post(
                f"https://api.x.com/oauth/{endpoint}", auth=auth, timeout=30, allow_redirects=False
            )
            response.raise_for_status()
            if response.status_code != 200:
                raise ValueError("Unexpected OAuth response")
            values = parse_qs(response.text)
            result = {key: value[0] for key, value in values.items() if len(value) == 1}
            if not all(result.get(key) for key in required):
                raise ValueError("Incomplete OAuth response")
            return result
        except (requests.RequestException, ValueError):
            raise ValidationError(
                "X could not authorize this connection. Please connect your X Ads account again."
            ) from None

    @classmethod
    def authorize_url(cls, team_id: int, user_id: int, next_url: str) -> str:
        cls.require_configured()
        if next_url and (
            not next_url.startswith("/") or not url_has_allowed_host_and_scheme(next_url, allowed_hosts=set())
        ):
            raise ValidationError("Invalid next URL")
        tokens = cls._exchange(
            "request_token",
            OAuth1(
                settings.TWITTER_ADS_CONSUMER_KEY,
                settings.TWITTER_ADS_CONSUMER_SECRET,
                callback_uri=OauthIntegration.redirect_uri("twitter-ads"),
            ),
            ("oauth_token", "oauth_token_secret", "oauth_callback_confirmed"),
        )
        if tokens["oauth_callback_confirmed"] != "true":
            raise ValidationError("X did not confirm the callback URL. Please try connecting again.")
        cache.set(
            cls.binding_key(tokens["oauth_token"]),
            {
                "oauth_token_secret": tokens["oauth_token_secret"],
                "team_id": team_id,
                "user_id": user_id,
                "next": next_url,
            },
            timeout=cls.binding_ttl,
        )
        return f"https://api.x.com/oauth/authorize?{urlencode({'oauth_token': tokens['oauth_token']})}"

    @classmethod
    def integration_from_callback(cls, team_id: int, user: "User", config: dict[str, object]) -> Integration:
        cls.require_configured()
        token = config.get("oauth_token")
        verifier = config.get("oauth_verifier")
        if not isinstance(token, str) or not token or not isinstance(verifier, str) or not verifier:
            raise ValidationError("X authorization token and verifier are required")
        key = cls.binding_key(token)
        binding = cache.get(key)
        if not binding or binding["team_id"] != team_id or binding["user_id"] != user.id:
            raise ValidationError(
                "X authorization expired or does not belong to this user and project. Please connect again."
            )
        # Atomic deletion lets only one callback exchange this grant, even if requests arrive together.
        if not cache.delete(key):
            raise ValidationError("X authorization has already been used. Please connect again.")
        tokens = cls._exchange(
            "access_token",
            OAuth1(
                settings.TWITTER_ADS_CONSUMER_KEY,
                settings.TWITTER_ADS_CONSUMER_SECRET,
                token,
                binding["oauth_token_secret"],
                verifier=verifier,
            ),
            ("oauth_token", "oauth_token_secret", "user_id", "screen_name"),
        )
        integration, _ = Integration.objects.update_or_create(
            team_id=team_id,
            kind="twitter-ads",
            integration_id=tokens["user_id"],
            defaults={
                "created_by": user,
                "config": {"screen_name": tokens["screen_name"], "user_id": tokens["user_id"], "next": binding["next"]},
                "sensitive_config": {
                    "oauth_token": tokens["oauth_token"],
                    "oauth_token_secret": tokens["oauth_token_secret"],
                },
            },
        )
        return integration
