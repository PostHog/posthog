"""Appearance schema shared by the API serializer and the remote config payload builder."""

ART_STYLE_NONE = "none"
ART_STYLE_POSTHOG_LOGO = "posthog-logo"
ART_STYLE_HEDGEHOG_BUILDER = "hedgehog-builder"
ART_STYLE_HEDGEHOG_BUSINESS = "hedgehog-business"
ART_STYLE_HEDGEHOG_HOGZILLA = "hedgehog-hogzilla"
ART_STYLE_HEDGEHOG_ROBOT = "hedgehog-robot"

ART_STYLES: list[str] = [
    ART_STYLE_NONE,
    ART_STYLE_POSTHOG_LOGO,
    ART_STYLE_HEDGEHOG_BUILDER,
    ART_STYLE_HEDGEHOG_BUSINESS,
    ART_STYLE_HEDGEHOG_HOGZILLA,
    ART_STYLE_HEDGEHOG_ROBOT,
]

POSITIONS: list[str] = ["bottom-left", "bottom-right", "bottom-bar"]

# Styled after the posthog.com cookie banner: cream background, near-black text,
# PostHog orange call to action.
DEFAULT_APPEARANCE: dict[str, str | bool] = {
    "title": "We use cookies",
    "description": "We use cookies to understand how you use our site and to improve your experience. You can accept or decline analytics cookies below.",
    "acceptButtonText": "Accept",
    "declineButtonText": "Decline",
    "artStyle": ART_STYLE_POSTHOG_LOGO,
    "position": "bottom-right",
    "backgroundColor": "#eeefe9",
    "textColor": "#151515",
    "buttonColor": "#f54e00",
    "buttonTextColor": "#ffffff",
    "whiteLabel": False,
}

MAX_TEXT_LENGTHS: dict[str, int] = {
    "title": 200,
    "description": 1000,
    "acceptButtonText": 100,
    "declineButtonText": 100,
}
