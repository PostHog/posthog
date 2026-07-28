"""Builds and syncs the standalone cookie banner artifact served at /array/{token}/cookie-banner.js.

The artifact is one HyperCache entry per team (`{"js": "<runtime>"}`), read by
hypercache-server's `cookie_banner_js_endpoint`. A disabled or absent banner stores
the missing sentinel, which the server turns into a 404.
"""

import re
from typing import TYPE_CHECKING, Any

from posthog.constants import AvailableFeature
from posthog.models.remote_config import purge_cdn_urls
from posthog.storage.hypercache import HyperCache, HyperCacheStoreMissing

from products.cookie_banner.backend.constants import (
    ART_STYLES,
    CATEGORY_KEY_REGEX,
    COLOR_KEYS,
    DEFAULT_APPEARANCE,
    DEFAULT_CATEGORIES,
    HEX_COLOR_REGEX,
    LANGUAGE_CODE_REGEX,
    MAX_CATEGORIES,
    MAX_CATEGORY_DESCRIPTION_LENGTH,
    MAX_CATEGORY_LABEL_LENGTH,
    MAX_TEXT_LENGTHS,
    MAX_TRANSLATION_LANGUAGES,
    POSITIONS,
    RESERVED_CATEGORY_KEYS,
    TRANSLATABLE_KEYS,
)
from products.cookie_banner.backend.models import CookieBannerConfig
from products.cookie_banner.backend.runtime import build_cookie_banner_runtime_js

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


def _sanitize_categories(raw: Any) -> list[dict[str, str]]:
    """Whitelist consent categories from the stored JSON: valid keys, bounded labels,
    no duplicates or reserved keys, and `analytics` always present (it drives
    posthog-js consent, so the runtime requires it)."""
    if not isinstance(raw, list):
        raw = []
    sanitized: list[dict[str, str]] = []
    seen: set[str] = set()
    for entry in raw:
        if len(sanitized) >= MAX_CATEGORIES:
            break
        if not isinstance(entry, dict):
            continue
        key = entry.get("key")
        label = entry.get("label")
        if not isinstance(key, str) or not re.match(CATEGORY_KEY_REGEX, key):
            continue
        if key in RESERVED_CATEGORY_KEYS or key in seen:
            continue
        if not isinstance(label, str) or not label or len(label) > MAX_CATEGORY_LABEL_LENGTH:
            continue
        item = {"key": key, "label": label}
        description = entry.get("description")
        if isinstance(description, str) and description and len(description) <= MAX_CATEGORY_DESCRIPTION_LENGTH:
            item["description"] = description
        sanitized.append(item)
        seen.add(key)
    if "analytics" not in seen:
        sanitized.insert(0, dict(DEFAULT_CATEGORIES[0]))
    return sanitized[:MAX_CATEGORIES]


def _build_client_config(team: "Team", config: CookieBannerConfig) -> dict[str, Any]:
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
    client_config["categories"] = _sanitize_categories(client_config["categories"])

    # Build-time enforcement on top of the API-level check: removing the "Powered by
    # PostHog" notice requires the white labelling entitlement *now*, so a downgraded
    # org's stale whiteLabel flag stops applying on the next artifact rebuild.
    client_config["whiteLabel"] = bool(client_config["whiteLabel"]) and team.organization.is_feature_available(
        AvailableFeature.WHITE_LABELLING
    )

    return client_config


def build_cookie_banner_artifact(team: "Team") -> dict[str, str] | HyperCacheStoreMissing:
    """Return the team's artifact payload, or the missing sentinel when no enabled banner exists."""
    # The team object is already in hand, so pre-resolve the canonical id instead of
    # letting for_team() pay an extra Team lookup on every rebuild
    canonical_team_id = team.parent_team_id or team.id
    config = CookieBannerConfig.objects.for_team(canonical_team_id, canonical=True).filter(enabled=True).first()
    if config is None:
        return HyperCacheStoreMissing()

    client_config = _build_client_config(team, config)
    return {"js": build_cookie_banner_runtime_js(client_config, team.api_token)}


cookie_banner_artifact_hypercache = HyperCache(
    namespace="array",
    value="cookie-banner.js",
    load_fn=lambda key: build_cookie_banner_artifact(HyperCache.team_from_key(key)),
    token_based=True,
)


def sync_cookie_banner_artifact(team: "Team") -> None:
    """Rebuild the team's cookie-banner.js cache entry and purge it from the CDN."""
    cookie_banner_artifact_hypercache.update_cache(team)
    purge_cdn_urls([f"/array/{team.api_token}/cookie-banner.js"])
