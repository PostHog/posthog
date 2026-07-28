"""Appearance schema shared by the API serializer and the artifact payload builder."""

# Values here must match the COOKIE_BANNER_ART keys in runtime.py and the
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

# Consent category keys: short, lowercase, usable in data-ph-consent attributes
CATEGORY_KEY_REGEX = r"^[a-z][a-z0-9_-]{0,31}$"
MAX_CATEGORIES = 10
MAX_CATEGORY_LABEL_LENGTH = 30
MAX_CATEGORY_DESCRIPTION_LENGTH = 120
# "necessary" is implicit and always-on; it can't be configured or declined
RESERVED_CATEGORY_KEYS: list[str] = ["necessary"]

DEFAULT_CATEGORIES: list[dict[str, str]] = [
    {"key": "analytics", "label": "Analytics"},
    {"key": "marketing", "label": "Marketing"},
]

# Styled after the posthog.com cookie banner: cream background, near-black text,
# PostHog orange call to action.
DEFAULT_APPEARANCE: dict[str, str | bool | dict | list] = {
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
    "googleConsentMode": False,
    "translations": {},
    "categories": DEFAULT_CATEGORIES,
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
