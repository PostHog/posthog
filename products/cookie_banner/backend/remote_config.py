"""Builds the cookie banner's siteAppsJS entry for a team's remote config payload."""

import re
from typing import TYPE_CHECKING, Any, Optional

from posthog.constants import AvailableFeature

from products.cookie_banner.backend.constants import (
    ART_STYLES,
    COLOR_KEYS,
    DEFAULT_APPEARANCE,
    HEX_COLOR_REGEX,
    LANGUAGE_CODE_REGEX,
    MAX_TEXT_LENGTHS,
    MAX_TRANSLATION_LANGUAGES,
    POSITIONS,
    TRANSLATABLE_KEYS,
)
from products.cookie_banner.backend.models import CookieBannerConfig
from products.cookie_banner.backend.site_app_js import build_cookie_banner_js

if TYPE_CHECKING:
    from posthog.models.team import Team


def _sanitize_translations(raw: Any) -> dict[str, dict[str, str]]:
    """Whitelist translation entries the same way the top-level appearance keys are:
    the stored JSON is user data and never ships to customer sites unvalidated."""
    if not isinstance(raw, dict):
        return {}
    sanitized: dict[str, dict[str, str]] = {}
    for language, overrides in raw.items():
        if len(sanitized) >= MAX_TRANSLATION_LANGUAGES:
            break
        if not isinstance(language, str) or not re.match(LANGUAGE_CODE_REGEX, language):
            continue
        if not isinstance(overrides, dict):
            continue
        entry = {
            key: value
            for key, value in overrides.items()
            if key in TRANSLATABLE_KEYS and isinstance(value, str) and len(value) <= MAX_TEXT_LENGTHS[key]
        }
        if entry:
            sanitized[language] = entry
    return sanitized


def build_cookie_banner_site_app_js(team: "Team") -> Optional[str]:
    """Return the banner's siteAppsJS entry, or None when no enabled banner exists.

    Called from RemoteConfig._build_site_apps_js on every config rebuild for the team.
    """
    # The team object is already in hand, so pre-resolve the canonical id instead of
    # letting for_team() pay an extra Team lookup on every rebuild
    canonical_team_id = team.parent_team_id or team.id
    config = CookieBannerConfig.objects.for_team(canonical_team_id, canonical=True).filter(enabled=True).first()
    if config is None:
        return None

    appearance = config.appearance if isinstance(config.appearance, dict) else {}
    client_config: dict[str, Any] = {}
    # Whitelist known keys and fall back to defaults on invalid values — the raw JSON
    # column is never passed through to customer sites, regardless of how it was written.
    for key, default in DEFAULT_APPEARANCE.items():
        value = appearance.get(key, default)
        client_config[key] = value if isinstance(value, type(default)) else default
    if client_config["artStyle"] not in ART_STYLES:
        client_config["artStyle"] = DEFAULT_APPEARANCE["artStyle"]
    if client_config["position"] not in POSITIONS:
        client_config["position"] = DEFAULT_APPEARANCE["position"]
    for key in COLOR_KEYS:
        if not re.match(HEX_COLOR_REGEX, client_config[key]):
            client_config[key] = DEFAULT_APPEARANCE[key]
    client_config["translations"] = _sanitize_translations(client_config["translations"])

    # Build-time enforcement on top of the API-level check: removing the "Powered by
    # PostHog" notice requires the white labelling entitlement *now*, so a downgraded
    # org's stale whiteLabel flag stops applying on the next config rebuild.
    client_config["whiteLabel"] = bool(client_config["whiteLabel"]) and team.organization.is_feature_available(
        AvailableFeature.WHITE_LABELLING
    )

    return build_cookie_banner_js(client_config)
