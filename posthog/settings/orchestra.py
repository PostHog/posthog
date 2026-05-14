from posthog.settings.utils import get_from_env, str_to_bool

ORCHESTRA_ENABLED: bool = get_from_env("ORCHESTRA_ENABLED", False, type_cast=str_to_bool)
ORCHESTRA_DSN: str = get_from_env(
    "ORCHESTRA_DSN",
    "postgres://posthog:posthog@localhost:5432/posthog_orchestra",
)
ORCHESTRA_POLL_INTERVAL: float = get_from_env("ORCHESTRA_POLL_INTERVAL", 0.5, type_cast=float)
ORCHESTRA_MAX_CONCURRENCY: int = get_from_env("ORCHESTRA_MAX_CONCURRENCY", 4, type_cast=int)
ORCHESTRA_LEASE_SECONDS: int = get_from_env("ORCHESTRA_LEASE_SECONDS", 30, type_cast=int)

# Image tag of the base runtime built by bin/build-orchestra-runtime. Per-deploy
# images FROM this and add the user's code.
ORCHESTRA_RUNTIME_IMAGE: str = get_from_env(
    "ORCHESTRA_RUNTIME_IMAGE",
    "posthog/orchestra-runtime:latest",
)
# Where extracted code archives + per-build Dockerfiles live on the host running
# the build (i.e. the dev box / PostHog process host).
ORCHESTRA_BUILD_DIR: str = get_from_env(
    "ORCHESTRA_BUILD_DIR",
    "/tmp/orchestra-builds",
)
# DSN injected into user containers. Default is empty — when empty,
# orchestra/backend/build.py derives it from ORCHESTRA_DSN by rewriting
# localhost / 127.0.0.1 to host.docker.internal.
ORCHESTRA_CONTAINER_DSN: str = get_from_env("ORCHESTRA_CONTAINER_DSN", "")
# Seconds between drain-check ticks for retired deployments.
ORCHESTRA_DRAIN_POLL_INTERVAL: float = get_from_env("ORCHESTRA_DRAIN_POLL_INTERVAL", 5.0, type_cast=float)
