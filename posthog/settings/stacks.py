import os

from posthog.settings.base_variables import DEBUG, TEST
from posthog.settings.utils import get_from_env, get_list, str_to_bool

# Fernet keys that encrypt each stack's record and its saved diffs at rest. Comma-separated, newest
# first: the first key encrypts, every key decrypts, so a rotation prepends a new key and runs
# `manage.py reencrypt_stack_records`. Each environment gets its own value. There is no SECRET_KEY
# fallback, so an unset value in production makes every encrypt and decrypt fail closed.
# The dev and test default is a fixed, public Fernet key that protects nothing.
STACKS_ENCRYPTION_KEYS: list[str] = get_list(
    os.getenv(
        "STACKS_ENCRYPTION_KEYS",
        "c3RhY2tzLWRldi1rZXktbm90LWEtc2VjcmV0LTAwMDA=" if (TEST or DEBUG) else "",
    )
)

# The worker image holds the engine binary and a filesystem mirror with the pinned provider, so a run
# never downloads anything. A local developer may fall back to the public registry instead.
STACKS_ENGINE_BINARY: str = os.getenv("STACKS_ENGINE_BINARY", "tofu")
STACKS_ENGINE_MIRROR: str = os.getenv("STACKS_ENGINE_MIRROR", "")
STACKS_ENGINE_ALLOW_REGISTRY: bool = get_from_env(
    "STACKS_ENGINE_ALLOW_REGISTRY", DEBUG and not TEST, type_cast=str_to_bool
)
STACKS_ENGINE_WORKDIR: str = os.getenv("STACKS_ENGINE_WORKDIR", "/tmp/posthog-stacks")
# The PostHog API base URL the engine calls. Empty means SITE_URL.
STACKS_ENGINE_API_HOST: str = os.getenv("STACKS_ENGINE_API_HOST", "")

# Whether the write lock asks the stacks database when its cached answer for a project is missing. Always on
# outside tests. Tests of other products run without the stacks database, so there a missing answer means no
# managed entity; the stacks tests turn it on.
STACKS_WRITE_LOCK_READS_DATABASE: bool = get_from_env(
    "STACKS_WRITE_LOCK_READS_DATABASE", not TEST, type_cast=str_to_bool
)
