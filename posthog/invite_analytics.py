import hashlib

# A fixed prefix keeps this hash apart from any other hash of the same id.
_PURPOSE = "posthog.invite_analytics:"


def invite_analytics_id(invite_id: object) -> str:
    """The invite id accepts the invite, so analytics and email telemetry get this hash of it instead.

    The hash reads no key, because `SECRET_KEY` takes no new purpose. An invite id has 64 random bits and expires
    after a few days, which is too short for a search over them.
    """
    return hashlib.sha256(f"{_PURPOSE}{invite_id}".encode()).hexdigest()[:32]


def invite_distinct_id(invite_id: object) -> str:
    return f"invite_{invite_analytics_id(invite_id)}"
