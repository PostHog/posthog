"""Appearance schema shared by the API serializer and the remote config payload builder."""

# Values here must match the COOKIE_BANNER_ART keys in site_app_js.py and the
# ART_STYLE_LABELS keys in frontend/constants.ts
ART_STYLES: list[str] = [
    "none",
    "posthog-logo",
    "posthog-logomark-light",
    "hedgehog-builder",
    "hedgehog-business",
    "hedgehog-hogzilla",
    "hedgehog-robot",
    "hedgehog-mobile",
    "hedgehog-zen",
    "hedgehog-lens",
    "hedgehog-town-crier",
    "hedgehog-wizard",
    "hedgehog-legal",
]

POSITIONS: list[str] = ["bottom-left", "bottom-right", "bottom-bar"]

HEX_COLOR_REGEX = r"^#(?:[0-9a-fA-F]{3,4}|[0-9a-fA-F]{6}|[0-9a-fA-F]{8})$"

# ISO 639 language code with an optional region subtag, e.g. "de" or "pt-BR"
LANGUAGE_CODE_REGEX = r"^[a-z]{2,3}(-[A-Za-z]{2})?$"

MAX_TRANSLATION_LANGUAGES = 20

# Styled after the posthog.com cookie banner: cream background, near-black text,
# PostHog orange call to action.
DEFAULT_APPEARANCE: dict[str, str | bool | dict] = {
    "title": "We use cookies",
    "description": "We use cookies to understand how you use our site and to improve your experience. You can accept or decline analytics cookies below.",
    "acceptButtonText": "Accept",
    "declineButtonText": "Decline",
    "preferencesButtonText": "Manage preferences",
    "artStyle": "posthog-logo",
    "position": "bottom-right",
    "backgroundColor": "#eeefe9",
    "textColor": "#151515",
    "buttonColor": "#f54e00",
    "buttonTextColor": "#ffffff",
    "whiteLabel": False,
    "showPreferences": False,
    "cookielessFallback": False,
    "respectGpc": True,
    "translations": {},
}

COLOR_KEYS: list[str] = ["backgroundColor", "textColor", "buttonColor", "buttonTextColor"]

MAX_TEXT_LENGTHS: dict[str, int] = {
    "title": 25,
    "description": 200,
    "acceptButtonText": 11,
    "declineButtonText": 11,
    "preferencesButtonText": 25,
}

# Appearance keys that can be overridden per language in `translations`
TRANSLATABLE_KEYS: list[str] = [
    "title",
    "description",
    "acceptButtonText",
    "declineButtonText",
    "preferencesButtonText",
]
