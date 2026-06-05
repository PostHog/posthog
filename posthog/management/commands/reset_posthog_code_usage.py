"""Reset PostHog Code usage / rate-limit counters in the llm-gateway Redis.

The PostHog Code cost limits and per-user request-rate limits live in the
llm-gateway service's dedicated Redis (the gateway connects to it via its own
``LLM_GATEWAY_REDIS_URL``). This is a SEPARATE ElastiCache cluster from
``AI_GATEWAY_REDIS_URL`` — the latter only holds the HyperCache policy blob and
does NOT contain rate-limit counters.

This command reads the URL from ``settings.LLM_GATEWAY_REDIS_URL`` (or a
``--redis-url`` override). That env var is not wired into Django pods by
default, so to run this in a deployed environment the operator must point it at
the gateway's Redis (and the pod must have network access to it). The gateway
writes raw ``ratelimit:*`` keys without a Django key prefix, so this command
talks to Redis directly rather than going through django_redis.

A per-user reset clears both the posthog_code cost counters and the user's
request-rate (burst/sustained) counters. Note the request-rate counters are
not product-scoped, so clearing them also lifts the user's request-rate limit
on other gateway products.

Mirrors services/llm-gateway/src/llm_gateway/cli/reset_posthog_code_usage.py —
keep both ends in sync if the cache key shape changes.
"""

from __future__ import annotations

import re

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError

import redis

# Mirrors POSTHOG_CODE_PRODUCT in the gateway. Client aliases (e.g. "array",
# "twig") are normalized to this before the cache key is built, so the stored
# keys always use "posthog_code".
POSTHOG_CODE_PRODUCT = "posthog_code"

# The two per-user cost throttles (_UserCostThrottleBase subclasses).
USER_COST_SCOPES = ("user_cost_burst", "user_cost_sustained")

# The two per-user request-rate scopes (RateLimiter). These are keyed by the
# authenticated user's id alone and are NOT product-scoped — resetting them
# clears the user's burst/sustained request-rate limit across every gateway
# product, not just posthog_code.
REQUEST_SCOPES = ("burst", "sustained")

SCAN_COUNT = 500
UNLINK_BATCH = 500

_REDIS_GLOB_METACHARS = re.compile(r"([\\*?\[\]])")


def _escape(user_id: str) -> str:
    # Escape glob metachars so a user_id like "10*" cannot expand the SCAN match
    # and wipe unrelated users' counters.
    return _REDIS_GLOB_METACHARS.sub(r"\\\1", user_id)


def _user_cost_patterns(user_id: str | None) -> tuple[str, ...]:
    """Cache-key globs for per-user cost counters.

    Mirrors _UserCostThrottleBase._get_cache_key (plus the outer "ratelimit:"
    added by redis_limiter, and the ":tm{n}" / ":period:{n}" suffixes).
    """
    if user_id is None:
        return tuple(f"ratelimit:cost:user:{scope}:{POSTHOG_CODE_PRODUCT}:*" for scope in USER_COST_SCOPES)

    safe_id = _escape(user_id)
    patterns: list[str] = []
    for scope in USER_COST_SCOPES:
        base = f"ratelimit:cost:user:{scope}:{POSTHOG_CODE_PRODUCT}:{safe_id}"
        # Bare base key, plus its colon-suffixed variants. The trailing ":"
        # stops user "100" from also matching user "1000".
        patterns.append(base)
        patterns.append(f"{base}:*")
    return tuple(patterns)


def _request_patterns(user_id: str | None) -> tuple[str, ...]:
    """Cache-key globs for the per-user request-rate counters.

    Mirrors RateLimiter.check: "ratelimit:{scope}:{user_id}". These are exact
    keys (no suffixes), so a single-user reset matches the escaped key exactly.
    """
    if user_id is None:
        return tuple(f"ratelimit:{scope}:*" for scope in REQUEST_SCOPES)
    safe_id = _escape(user_id)
    return tuple(f"ratelimit:{scope}:{safe_id}" for scope in REQUEST_SCOPES)


def _product_patterns() -> tuple[str, ...]:
    """Cache-key globs for the product-wide aggregate cost pool (shared by everyone)."""
    base = f"ratelimit:cost:product:{POSTHOG_CODE_PRODUCT}"
    return (base, f"{base}:tm*")


def reset_keys(client: redis.Redis, patterns: tuple[str, ...], *, dry_run: bool) -> int:
    """SCAN each pattern and UNLINK the matches in batches. Returns keys affected."""
    affected = 0
    for pattern in patterns:
        batch: list[bytes] = []
        for key in client.scan_iter(match=pattern, count=SCAN_COUNT):
            batch.append(key)
            if len(batch) >= UNLINK_BATCH:
                affected += _flush(client, batch, dry_run=dry_run)
        if batch:
            affected += _flush(client, batch, dry_run=dry_run)
    return affected


def _flush(client: redis.Redis, batch: list[bytes], *, dry_run: bool) -> int:
    n = len(batch)
    if not dry_run:
        client.unlink(*batch)
    batch.clear()
    return n


class Command(BaseCommand):
    help = "Reset PostHog Code usage and per-user request-rate limit counters in the LLM gateway Redis"

    def add_arguments(self, parser):
        parser.add_argument(
            "--user-id",
            action="append",
            dest="user_ids",
            metavar="ID",
            help="Reset this user's posthog_code cost counters and request-rate (burst/sustained) counters. Repeatable.",
        )
        parser.add_argument(
            "--all-users",
            action="store_true",
            help="Reset the cost counters and request-rate counters for every user.",
        )
        parser.add_argument(
            "--product-total",
            action="store_true",
            help="Also reset the product-wide aggregate cost pool (affects all users).",
        )
        parser.add_argument(
            "--cost",
            action="store_true",
            help="Reset only the posthog_code cost counters. Combine with --request to reset both; "
            "if neither is given, both are reset.",
        )
        parser.add_argument(
            "--request",
            action="store_true",
            help="Reset only the per-user request-rate (burst/sustained) counters. Combine with --cost "
            "to reset both; if neither is given, both are reset.",
        )
        parser.add_argument(
            "--redis-url",
            help="Override the llm-gateway Redis URL (defaults to settings.LLM_GATEWAY_REDIS_URL).",
        )
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Count matching keys without deleting anything.",
        )

    def handle(self, *args, **options):
        user_ids: list[str] | None = options["user_ids"]
        all_users: bool = options["all_users"]
        product_total: bool = options["product_total"]
        dry_run: bool = options["dry_run"]

        # When neither type is named, reset both. --product-total is a cost-side
        # pool and is controlled by its own flag, independent of these.
        reset_cost: bool = options["cost"] or not options["request"]
        reset_request: bool = options["request"] or not options["cost"]

        if user_ids and all_users:
            raise CommandError("Pass either --user-id or --all-users, not both.")
        if not (user_ids or all_users or product_total):
            raise CommandError("Specify at least one of --user-id, --all-users, or --product-total.")

        for user_id in user_ids or []:
            if not user_id.strip():
                raise CommandError("--user-id cannot be empty.")

        redis_url = options["redis_url"] or settings.LLM_GATEWAY_REDIS_URL
        if not redis_url:
            raise CommandError(
                "No llm-gateway Redis URL — set LLM_GATEWAY_REDIS_URL or pass --redis-url. "
                "Note this is the gateway's rate-limit cluster, not AI_GATEWAY_REDIS_URL."
            )

        client = redis.from_url(redis_url)
        mode = "DRY RUN" if dry_run else "EXECUTED"
        total = 0

        # (label, user_id) for each user-scoped target.
        targets: list[tuple[str, str | None]]
        if user_ids:
            targets = [(f"user {user_id}", user_id) for user_id in user_ids]
        elif all_users:
            targets = [("all users", None)]
        else:
            targets = []

        for label, user_id in targets:
            if reset_cost:
                deleted = reset_keys(client, _user_cost_patterns(user_id), dry_run=dry_run)
                total += deleted
                self.stdout.write(f"[{mode}] {label} cost: {deleted} keys")
            if reset_request:
                deleted = reset_keys(client, _request_patterns(user_id), dry_run=dry_run)
                total += deleted
                self.stdout.write(f"[{mode}] {label} request-rate: {deleted} keys")

        if product_total:
            deleted = reset_keys(client, _product_patterns(), dry_run=dry_run)
            total += deleted
            self.stdout.write(f"[{mode}] product-wide cost pool: {deleted} keys")

        summary = f"[{mode}] reset posthog_code limits: {total} keys total"
        self.stdout.write(self.style.SUCCESS(summary) if not dry_run else summary)
