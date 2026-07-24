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
]

POSITIONS: list[str] = ["bottom-left", "bottom-right", "bottom-bar"]

HEX_COLOR_REGEX = r"^#(?:[0-9a-fA-F]{3,4}|[0-9a-fA-F]{6}|[0-9a-fA-F]{8})$"

# Styled after the posthog.com cookie banner: cream background, near-black text,
# PostHog orange call to action.
DEFAULT_APPEARANCE: dict[str, str | bool] = {
    "title": "We use cookies",
    "description": "We use cookies to understand how you use our site and to improve your experience. You can accept or decline analytics cookies below.",
    "acceptButtonText": "Accept",
    "declineButtonText": "Decline",
    "artStyle": "posthog-logo",
    "position": "bottom-right",
    "backgroundColor": "#eeefe9",
    "textColor": "#151515",
    "buttonColor": "#f54e00",
    "buttonTextColor": "#ffffff",
    "whiteLabel": False,
}

COLOR_KEYS: list[str] = ["backgroundColor", "textColor", "buttonColor", "buttonTextColor"]

MAX_TEXT_LENGTHS: dict[str, int] = {
    "title": 200,
    "description": 1000,
    "acceptButtonText": 100,
    "declineButtonText": 100,
}
