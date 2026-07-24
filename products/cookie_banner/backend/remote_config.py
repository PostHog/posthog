"""Builds the cookie banner's siteAppsJS entry for a team's remote config payload."""

from typing import TYPE_CHECKING, Any, Optional

from posthog.constants import AvailableFeature

from products.cookie_banner.backend.constants import ART_STYLES, DEFAULT_APPEARANCE, POSITIONS
from products.cookie_banner.backend.models import CookieBannerConfig
from products.cookie_banner.backend.site_app_js import build_cookie_banner_js

if TYPE_CHECKING:
    from posthog.models.team import Team


def build_cookie_banner_site_app_js(team: "Team") -> Optional[str]:
    """Return the banner's siteAppsJS entry, or None when no enabled banner exists.

    Called from RemoteConfig._build_site_apps_js on every config rebuild for the team.
    """
    config = CookieBannerConfig.objects.for_team(team.id).filter(enabled=True).first()
    if config is None:
        return None

    appearance = config.appearance if isinstance(config.appearance, dict) else {}
    client_config: dict[str, Any] = {}
    # Whitelist known keys and fall back to defaults on type mismatches — the raw JSON
    # column is never passed through to customer sites.
    for key, default in DEFAULT_APPEARANCE.items():
        value = appearance.get(key, default)
        client_config[key] = value if isinstance(value, type(default)) else default
    if client_config["artStyle"] not in ART_STYLES:
        client_config["artStyle"] = DEFAULT_APPEARANCE["artStyle"]
    if client_config["position"] not in POSITIONS:
        client_config["position"] = DEFAULT_APPEARANCE["position"]

    # Build-time enforcement on top of the API-level check: removing the "Powered by
    # PostHog" notice requires the white labelling entitlement *now*, so a downgraded
    # org's stale whiteLabel flag stops applying on the next config rebuild.
    client_config["whiteLabel"] = bool(client_config["whiteLabel"]) and team.organization.is_feature_available(
        AvailableFeature.WHITE_LABELLING
    )

    return build_cookie_banner_js(client_config)
