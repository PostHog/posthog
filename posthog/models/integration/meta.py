"""Meta Graph API integrations (Meta Ads, Instagram) and their shared token refresh."""

import time

import requests
import structlog

from . import common, model, oauth, refresh_tracking

logger = structlog.get_logger(__name__)


class MetaGraphIntegration:
    """Token handling shared by the Meta Graph OAuth kinds (Meta Ads, Instagram).

    Meta issues no refresh token: a long-lived user access token is swapped for a fresh one
    through the `fb_exchange_token` grant, which is why these kinds sit outside the generic
    `OauthIntegration` refresh sweep and refresh on use instead.
    """

    integration: model.Integration
    kind: str = ""
    api_version: str = common.META_GRAPH_API_VERSION

    def __init__(self, integration: model.Integration) -> None:
        if integration.kind != self.kind:
            raise Exception(f"{type(self).__name__} init called with Integration with wrong 'kind'")
        self.integration = integration

    def refresh_access_token(self):
        oauth_config = oauth.OauthIntegration.oauth_config_for_kind(self.integration.kind)

        # skip refresh if more than 7 days until expiry
        if self.integration.config.get("expires_in") and self.integration.config.get("refreshed_at"):
            if (
                time.time()
                < self.integration.config.get("refreshed_at") + self.integration.config.get("expires_in") - 604800
            ):
                return

        res = requests.post(
            oauth_config.token_url,
            data={
                "client_id": oauth_config.client_id,
                "client_secret": oauth_config.client_secret,
                "fb_exchange_token": self.integration.sensitive_config["access_token"],
                "grant_type": "fb_exchange_token",
                "set_token_expires_in_60_days": True,
            },
            timeout=10,
        )

        try:
            config: dict = res.json()
        except ValueError:
            config = {}

        if res.status_code != 200 or not config.get("access_token"):
            logger.warning(f"Failed to refresh token for {self}", response=res.text)
            self.integration.errors = common.ERROR_TOKEN_REFRESH_FAILED
            reason = refresh_tracking.oauth_refresh_failure_reason(res.status_code, config, kind=self.integration.kind)
            attempt = refresh_tracking.record_refresh_failure(self.integration, reason=reason)
            refresh_tracking.oauth_refresh_counter.labels(
                kind=self.integration.kind, result="failed", reason=reason, attempt=attempt
            ).inc()
        else:
            logger.info(f"Refreshed access token for {self}")
            refresh_tracking.record_refresh_success(self.integration)
            self.integration.sensitive_config["access_token"] = config["access_token"]
            self.integration.errors = ""
            self.integration.config["expires_in"] = config.get("expires_in")
            self.integration.config["refreshed_at"] = int(time.time())
            # not used in CDP yet
            # reload_integrations_on_workers(self.integration.team_id, [self.integration.id])
            refresh_tracking.oauth_refresh_counter.labels(
                kind=self.integration.kind, result="success", reason="", attempt=""
            ).inc()
        self.integration.save()


class MetaAdsIntegration(MetaGraphIntegration):
    kind = "meta-ads"


class InstagramIntegration(MetaGraphIntegration):
    kind = "instagram"
