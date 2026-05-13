from posthog.settings.utils import get_from_env, str_to_bool

ORCHESTRA_ENABLED: bool = get_from_env("ORCHESTRA_ENABLED", False, type_cast=str_to_bool)
ORCHESTRA_DSN: str = get_from_env(
    "ORCHESTRA_DSN",
    "postgres://posthog:posthog@localhost:5432/posthog_orchestra",
)
ORCHESTRA_POLL_INTERVAL: float = get_from_env("ORCHESTRA_POLL_INTERVAL", 0.5, type_cast=float)
ORCHESTRA_MAX_CONCURRENCY: int = get_from_env("ORCHESTRA_MAX_CONCURRENCY", 4, type_cast=int)
ORCHESTRA_LEASE_SECONDS: int = get_from_env("ORCHESTRA_LEASE_SECONDS", 30, type_cast=int)
