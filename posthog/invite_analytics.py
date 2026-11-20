from django.utils.crypto import salted_hmac

# Keyed, because an invite id carries its creation time and has only 64 random bits.
_KEY_SALT = "posthog.invite_analytics"


def invite_analytics_id(invite_id: object) -> str:
    """The invite id accepts the invite, so analytics and email telemetry get this hash of it instead.

    The invite, its alias and its emails all run in the invite's own region, so they derive the same value.
    """
    return salted_hmac(_KEY_SALT, str(invite_id), algorithm="sha256").hexdigest()[:32]


def invite_distinct_id(invite_id: object) -> str:
    return f"invite_{invite_analytics_id(invite_id)}"
