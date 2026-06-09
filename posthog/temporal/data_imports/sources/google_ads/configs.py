"""Lightweight Google Ads config classes.

Kept separate from ``google_ads.py`` so importing the source for registration
(``SourceRegistry`` / ``load_all_sources``) does not drag the ``google-ads`` SDK.
The SDK has a circular module graph that is only safe to import single-threaded;
importing it from concurrent worker threads can deadlock or duplicate-register its
protobuf descriptors. Nothing here imports the SDK — that import is deferred to the
run path in ``source.py``. See ``google_ads.py`` for the SDK-backed functions.
"""

import dataclasses

from posthog.temporal.data_imports.sources.common import config
from posthog.temporal.data_imports.sources.generated_configs import GoogleAdsSourceConfig


@dataclasses.dataclass
class GoogleAdsResumeConfig:
    """Resumable state for the Google Ads source.

    `page_token` is the opaque continuation token returned by
    `GoogleAdsService.search` for the next page to fetch.
    """

    page_token: str


def clean_customer_id(s: str | None) -> str | None:
    """Clean customer IDs from Google Ads.

    Customer IDs can contain dashes, but we need the ID without them.
    """
    if not s:
        return s

    return s.strip().replace("-", "")


@config.config
class GoogleAdsServiceAccountSourceConfig(config.Config):
    """Google Ads source config using service account for authentication.

    Old config for when we were using a service account instead of oauth.
    ~100 sources still use this method for auth. We recommend using
    `GoogleAdsSourceConfig` instead"""

    customer_id: str = config.value(converter=clean_customer_id)

    private_key: str = config.value(
        default_factory=config.default_from_settings("GOOGLE_ADS_SERVICE_ACCOUNT_PRIVATE_KEY")
    )
    private_key_id: str = config.value(
        default_factory=config.default_from_settings("GOOGLE_ADS_SERVICE_ACCOUNT_PRIVATE_KEY_ID")
    )
    client_email: str = config.value(
        default_factory=config.default_from_settings("GOOGLE_ADS_SERVICE_ACCOUNT_CLIENT_EMAIL")
    )
    token_uri: str = config.value(default_factory=config.default_from_settings("GOOGLE_ADS_SERVICE_ACCOUNT_TOKEN_URI"))
    developer_token: str = config.value(default_factory=config.default_from_settings("GOOGLE_ADS_DEVELOPER_TOKEN"))


GoogleAdsSourceConfigUnion = GoogleAdsServiceAccountSourceConfig | GoogleAdsSourceConfig
