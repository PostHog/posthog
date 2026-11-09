"""Core Django system checks, and the ID scheme every PostHog system check follows.

A system check catches a deployment misconfiguration when the process starts (`migrate`, `check`,
`runserver`) instead of in user traffic. Each check ID has the form `posthog.<area>.<level><nnn>`:

- `<area>` names what the check guards, such as `oauth` or `storage`. A product check uses the
  product name, such as `posthog.canvas.E001`.
- `<level>` is `E` for an error, which stops `migrate` and `runserver`, or `W` for a warning,
  which only prints.
- `<nnn>` counts up from 001 inside each area and level. Never reuse a retired number.

Core checks live in this module, grouped by area. A product check lives in its product's
`backend/checks.py` and registers through `register_check` from this module. Declare every ID a
check can emit in `register_check`, so `test_system_check_ids.py` can verify them from Django's
check registry without running the check.
"""

import re
import ipaddress
from collections.abc import Callable, Sequence
from typing import Any

from django.conf import settings
from django.contrib.auth.models import Group as AuthGroup
from django.core.checks import CheckMessage, Error, Tags, Warning, register
from django.db import DEFAULT_DB_ALIAS, DatabaseError

from posthog.models.oauth import oidc_signing_key_configured
from posthog.product_db_router import get_product_db_routes
from posthog.storage.object_storage import is_usable_endpoint
from posthog.utils import parse_crontab

CHECK_ID_PATTERN = re.compile(r"^posthog\.[a-z][a-z0-9_]*\.[EW]\d{3}$")

CheckFunction = Callable[..., list[CheckMessage]]


def register_check(*check_ids: str, tags: Sequence[str] = ()) -> Callable[[CheckFunction], CheckFunction]:
    def decorator(check: CheckFunction) -> CheckFunction:
        setattr(check, "check_ids", check_ids)  # noqa: B010
        return register(*tags)(check)

    return decorator


# OAuth

OAUTH_SIGNING_KEY_MISSING = "posthog.oauth.W001"


@register_check(OAUTH_SIGNING_KEY_MISSING)
def check_oidc_signing_key(app_configs: Any, **kwargs: Any) -> list[CheckMessage]:
    if oidc_signing_key_configured():
        return []
    return [
        Warning(
            "OIDC_RSA_PRIVATE_KEY is not set, so OAuth clients cannot be created. "
            "MCP clients, dynamic client registration and toolbar sign-in fail with an OAuth server_error.",
            hint="Set OIDC_RSA_PRIVATE_KEY to an RSA private key in PEM format, for example the output of "
            "`openssl genrsa 2048`.",
            id=OAUTH_SIGNING_KEY_MISSING,
        )
    ]


# Object storage

STORAGE_PUBLIC_ENDPOINT_UNUSABLE = "posthog.storage.E001"


@register_check(STORAGE_PUBLIC_ENDPOINT_UNUSABLE)
def check_object_storage_public_endpoint(app_configs: Any, **kwargs: Any) -> list[CheckMessage]:
    """Catch a misconfigured OBJECT_STORAGE_PUBLIC_ENDPOINT at startup rather than in user traffic.

    An unsubstituted deployment template literal (e.g. `https://${POSTHOG_DOMAIN}`) makes boto3
    raise `ValueError` on client construction, which previously surfaced as 500s on every
    hypercache-backed read. Failing the system check makes the bad rollout obvious immediately.
    """
    errors: list[CheckMessage] = []

    endpoint = settings.OBJECT_STORAGE_PUBLIC_ENDPOINT
    if settings.OBJECT_STORAGE_ENABLED and endpoint and not is_usable_endpoint(endpoint):
        errors.append(
            Error(
                f"OBJECT_STORAGE_PUBLIC_ENDPOINT is not a usable URL: {endpoint!r}",
                hint="Check the deployment env — it likely contains an unsubstituted ${...} template placeholder.",
                id=STORAGE_PUBLIC_ENDPOINT_UNUSABLE,
            )
        )

    return errors


# Field encryption

ENCRYPTION_SALT_KEY_WRONG_LENGTH = "posthog.encryption.E001"


@register_check(ENCRYPTION_SALT_KEY_WRONG_LENGTH)
def check_encryption_salt_keys(app_configs: Any, **kwargs: Any) -> list[CheckMessage]:
    # Each ENCRYPTION_SALT_KEYS entry is used directly as a Fernet key, which must be exactly 32 bytes.
    # A wrong-length key otherwise fails lazily with an opaque error on the first encrypt/decrypt — and
    # during a SECRET_KEY / ENCRYPTION_SALT_KEYS rotation that surfaces as a confusing runtime crash
    # instead of a clear config error. SECRET_KEY / SALT_KEY are exempt: they run through PBKDF2, which
    # normalizes any input length to 32 bytes.
    errors: list[CheckMessage] = []
    for index, key in enumerate(settings.ENCRYPTION_SALT_KEYS):
        byte_length = len(key.encode("utf-8"))
        if byte_length != 32:
            errors.append(
                Error(
                    f"ENCRYPTION_SALT_KEYS[{index}] must be exactly 32 bytes, got {byte_length}.",
                    hint="Generate one with `openssl rand -hex 16` (produces 32 characters).",
                    id=ENCRYPTION_SALT_KEY_WRONG_LENGTH,
                )
            )
    return errors


# Product database routing

DB_ROUTER_APP_ON_SEVERAL_DATABASES = "posthog.db_router.E001"


@register_check(DB_ROUTER_APP_ON_SEVERAL_DATABASES)
def check_product_db_routes(app_configs: Any, **kwargs: Any) -> list[CheckMessage]:
    errors: list[CheckMessage] = []

    app_label_to_database: dict[str, str] = {}

    for route in get_product_db_routes():
        existing = app_label_to_database.get(route.app_label)
        if existing is not None and existing != route.database:
            errors.append(
                Error(
                    f"product db route for '{route.app_label}' points to multiple databases",
                    hint="Ensure each product app has exactly one database in db_routing.yaml",
                    id=DB_ROUTER_APP_ON_SEVERAL_DATABASES,
                )
            )
        app_label_to_database[route.app_label] = route.database

    return errors


# Network access

ACCESS_ALLOWED_IP_BLOCK_INVALID = "posthog.access.W001"
ACCESS_TRUSTED_PROXY_NOT_AN_IP = "posthog.access.W002"


@register_check(ACCESS_ALLOWED_IP_BLOCK_INVALID)
def check_allowed_ip_blocks(app_configs: Any, **kwargs: Any) -> list[CheckMessage]:
    # AllowIPMiddleware parses each block on every request, so one bad entry turns every request
    # outside the always-allowed paths into a 500 while startup succeeds.
    invalid = []
    for block in settings.ALLOWED_IP_BLOCKS:
        try:
            ipaddress.ip_network(block, strict=False)
        except ValueError:
            invalid.append(block)
    if not invalid:
        return []
    return [
        Warning(
            f"ALLOWED_IP_BLOCKS has entries that are not IP networks: {', '.join(repr(b) for b in invalid)}. "
            "Every request outside the always-allowed paths fails with a 500.",
            hint="Use an IP address or CIDR block for each entry, for example 10.0.0.0/8.",
            id=ACCESS_ALLOWED_IP_BLOCK_INVALID,
        )
    ]


@register_check(ACCESS_TRUSTED_PROXY_NOT_AN_IP)
def check_trusted_proxies(app_configs: Any, **kwargs: Any) -> list[CheckMessage]:
    # get_trusted_client_ip compares each proxy's IP to these entries as exact strings, so an entry
    # that is not a single IP (a CIDR block, a port, brackets) never matches and the client IP is lost.
    if settings.TRUST_ALL_PROXIES or not settings.TRUSTED_PROXIES:
        return []
    invalid = []
    for proxy in (p.strip() for p in settings.TRUSTED_PROXIES.split(",")):
        if not proxy:
            continue
        try:
            ipaddress.ip_address(proxy)
        except ValueError:
            invalid.append(proxy)
    if not invalid:
        return []
    return [
        Warning(
            f"TRUSTED_PROXIES has entries that are not single IP addresses: {', '.join(repr(p) for p in invalid)}. "
            "Requests through them get no client IP, so the IP allowlist rejects them and IP rate limits "
            "share one bucket.",
            hint="List each proxy's IP address. CIDR blocks and ports are not supported.",
            id=ACCESS_TRUSTED_PROXY_NOT_AN_IP,
        )
    ]


# Scheduled tasks

SCHEDULES_CRON_UNPARSEABLE = "posthog.schedules.W001"

CRON_SCHEDULE_SETTINGS = (
    "CALCULATE_COHORTS_DAY_SCHEDULE",
    "CALCULATE_COHORTS_NIGHT_SCHEDULE",
    "CLEAR_CLICKHOUSE_REMOVED_DATA_SCHEDULE_CRON",
    "CLEAR_CLICKHOUSE_DELETED_PERSON_SCHEDULE_CRON",
    "MATERIALIZE_COLUMNS_SCHEDULE_CRON",
)


@register_check(SCHEDULES_CRON_UNPARSEABLE)
def check_cron_schedules(app_configs: Any, **kwargs: Any) -> list[CheckMessage]:
    # get_crontab swallows a parse failure and returns None, so the Celery beat job is never scheduled
    # and nothing tells the operator. An empty value is a deliberate opt-out, so only non-empty values count.
    warnings: list[CheckMessage] = []
    for name in CRON_SCHEDULE_SETTINGS:
        schedule = getattr(settings, name, None)
        if not schedule:
            continue
        try:
            parse_crontab(schedule)
        except Exception:
            warnings.append(
                Warning(
                    f"{name} is not a valid cron schedule: {schedule!r}. The scheduled task never runs.",
                    hint="Use five fields separated by single spaces, for example '0 5 * * SAT'.",
                    id=SCHEDULES_CRON_UNPARSEABLE,
                )
            )
    return warnings


# Temporal

TEMPORAL_CLIENT_TLS_PAIR_INCOMPLETE = "posthog.temporal.W001"


@register_check(TEMPORAL_CLIENT_TLS_PAIR_INCOMPLETE)
def check_temporal_client_tls(app_configs: Any, **kwargs: Any) -> list[CheckMessage]:
    # The Temporal client enables TLS only when both values are set. With one of them, it connects in
    # plaintext, and a server that requires mutual TLS rejects the first workflow start at request time.
    if bool(settings.TEMPORAL_CLIENT_CERT) == bool(settings.TEMPORAL_CLIENT_KEY):
        return []
    present, missing = (
        ("TEMPORAL_CLIENT_CERT", "TEMPORAL_CLIENT_KEY")
        if settings.TEMPORAL_CLIENT_CERT
        else ("TEMPORAL_CLIENT_KEY", "TEMPORAL_CLIENT_CERT")
    )
    return [
        Warning(
            f"{present} is set but {missing} is not, so the Temporal client connects without TLS.",
            hint=f"Set {missing} too, or unset {present} if the Temporal server does not use mutual TLS.",
            id=TEMPORAL_CLIENT_TLS_PAIR_INCOMPLETE,
        )
    ]


# Admin console

ADMIN_CONSOLE_STAFF_GROUP_MISSING = "posthog.admin_console.W001"


@register_check(ADMIN_CONSOLE_STAFF_GROUP_MISSING, tags=[Tags.database])
def check_admin_console_staff_groups(
    app_configs: Any, databases: Sequence[str] | None = None, **kwargs: Any
) -> list[CheckMessage]:
    # Gate.owner() lets in only the members of the owner's staff group, so a group that does not exist keeps every
    # staff member out of that team's gated operations. The database tag makes Django run this check only for
    # `manage.py check --database default` and `migrate`, never at startup.
    if not databases or DEFAULT_DB_ALIAS not in databases:
        return []
    # The console registry imports every console panel and tool, which the lazy admin keeps off django.setup().
    from posthog.admin.console.registry import console  # noqa: PLC0415

    staff_groups = console.staff_groups()
    try:
        existing = set(AuthGroup.objects.filter(name__in=staff_groups).values_list("name", flat=True))
    except DatabaseError:
        # `migrate` runs the checks before it creates the tables, so the groups table can be missing.
        return []
    return [
        Warning(
            f"The admin console gates operations on the {name!r} group, which does not exist. "
            "Nobody can run those operations.",
            hint=f"Create the {name!r} group in Django admin and add the staff who run them.",
            id=ADMIN_CONSOLE_STAFF_GROUP_MISSING,
        )
        for name in sorted(staff_groups - existing)
    ]
