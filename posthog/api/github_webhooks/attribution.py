from collections.abc import Iterator
from contextlib import ExitStack, contextmanager

from django.conf import settings
from django.db import OperationalError, connections, router, transaction
from django.db.backends.base.base import BaseDatabaseWrapper

import structlog
from social_django.models import UserSocialAuth

from posthog.api.github_webhooks.metrics import GitHubWebhookAttributionOutcome, observe_github_webhook_attribution
from posthog.models.integration import Integration
from posthog.models.organization import OrganizationMembership
from posthog.models.team.team import Team
from posthog.models.user import User
from posthog.models.user_integration import UserIntegration

from products.signals.backend.facade.github import resolve_github_login_distinct_id

logger = structlog.get_logger(__name__)

# Cap the org-member lookup that attributes the merger (and reviewer). GitHub gives a
# pull_request delivery one short window and never retries it, and the merged branch runs
# functional side effects (merge bookkeeping, signal-report resolution, wizard wind-down)
# right after capture. A slow lookup on the request path can therefore cost the whole
# delivery, not just the analytics event. Bounding it degrades to no attribution instead.
_ATTRIBUTION_STATEMENT_TIMEOUT_MS = 800

# Models the org-member resolver reads. ReplicaRouter only sends a model to the replica when
# that model is named in READ_REPLICA_OPT_IN, so the set of aliases the lookup can touch is
# knowable up front.
_ATTRIBUTION_MODELS = (Team, User, OrganizationMembership, UserSocialAuth, UserIntegration, Integration)


def _attribution_db_aliases() -> list[str]:
    """The aliases the org-member lookup actually reads from, deduped, in model order.

    Bounding an alias means opening it, and opening is itself unbounded -- ``postgres_config``
    sets no ``connect_timeout`` on these aliases. So take the set from the router rather than
    assuming: reaching for an alias the resolver never uses could stall the webhook on
    connection setup before the cap is installed, which is the failure this exists to prevent.
    That cuts both ways -- a fully replica-opted deployment must not be made to wait on the
    primary either.
    """
    aliases: list[str] = []
    for model in _ATTRIBUTION_MODELS:
        alias = router.db_for_read(model) or "default"
        if alias not in aliases and alias in settings.DATABASES:
            aliases.append(alias)
    return aliases


def _read_statement_timeout(connection: BaseDatabaseWrapper) -> str | None:
    with connection.cursor() as cursor:
        cursor.execute("SHOW statement_timeout")
        row = cursor.fetchone()
    return row[0] if row else None


def _apply_statement_timeout(connection: BaseDatabaseWrapper, value: str) -> None:
    # set_config(..., is_local=True) is SET LOCAL, but takes the value as a bind parameter,
    # so a restored value ("30s", "0", ...) does not have to be quoted by hand.
    with connection.cursor() as cursor:
        cursor.execute("SELECT set_config('statement_timeout', %s, true)", [value])


@contextmanager
def _statement_timeout(connection: BaseDatabaseWrapper, timeout_ms: int, *, restore: bool) -> Iterator[None]:
    """Cap statements on one connection, optionally putting the previous value back."""
    previous = _read_statement_timeout(connection) if restore else None
    _apply_statement_timeout(connection, f"{timeout_ms}ms")

    yield

    # Only reached when the block succeeded. If it raised, the enclosing atomic() rolls the
    # (sub)transaction back and PostgreSQL undoes SET LOCAL with it, so there is nothing to
    # restore -- and a statement on an aborted transaction would error anyway.
    if previous:
        _apply_statement_timeout(connection, previous)


@contextmanager
def _bounded_attribution_lookup() -> Iterator[None]:
    """Run a block under a per-statement timeout on each configured DB the lookup may use.

    A read routed to an alias joins that alias's open transaction, so ``SET LOCAL
    statement_timeout`` there caps the query regardless of read-replica routing.
    """
    with ExitStack() as stack:
        for alias in _attribution_db_aliases():
            connection = connections[alias]
            # SET LOCAL dies with the transaction it was set in, so the cap only needs
            # restoring when we are joining a transaction somebody else owns -- a future
            # caller wrapping this in its own atomic block, or ATOMIC_REQUESTS (which
            # PostHog does not enable today). Otherwise the commit below ends it for us.
            restore = connection.in_atomic_block
            stack.enter_context(transaction.atomic(using=alias))
            stack.enter_context(_statement_timeout(connection, _ATTRIBUTION_STATEMENT_TIMEOUT_MS, restore=restore))
        yield


# PostgreSQL raises query_canceled when statement_timeout fires. Django wraps the driver
# error in OperationalError, so the SQLSTATE lives on the cause -- psycopg3 spells it
# `sqlstate`, psycopg2 `pgcode`. The message check is the fallback for anything that loses
# the cause on the way up.
_QUERY_CANCELED_SQLSTATE = "57014"


def _is_statement_timeout(error: Exception) -> bool:
    if not isinstance(error, OperationalError):
        return False
    cause = error.__cause__
    if getattr(cause, "sqlstate", None) == _QUERY_CANCELED_SQLSTATE:
        return True
    if getattr(cause, "pgcode", None) == _QUERY_CANCELED_SQLSTATE:
        return True
    return "statement timeout" in str(error).lower()


def _resolve_github_login_distinct_id(login: str | None, team_id: int) -> str | None:
    """Distinct id of the org member matching a GitHub login, or None when unresolvable.

    Runs under a per-statement timeout so a slow member lookup cannot hold the webhook
    open past GitHub's delivery timeout (see ``_ATTRIBUTION_STATEMENT_TIMEOUT_MS``).
    """
    if not login:
        return None
    try:
        with _bounded_attribution_lookup():
            resolved = resolve_github_login_distinct_id(str(login), team_id)
    except Exception as e:
        # timeout is meant to be the leading indicator for the cap we just installed, so it
        # has to mean "statement cancelled", not "any OperationalError" -- connection resets
        # and other DB incidents raise the same class and would drown the signal.
        outcome: GitHubWebhookAttributionOutcome = "timeout" if _is_statement_timeout(e) else "error"
        observe_github_webhook_attribution(outcome=outcome)
        logger.warning(
            "github_webhook_login_resolution_failed", login=login, team_id=team_id, outcome=outcome, error=str(e)
        )
        return None
    if resolved is None:
        observe_github_webhook_attribution(outcome="unresolved")
        return None
    observe_github_webhook_attribution(outcome="resolved")
    return resolved


def _merged_by_attribution(payload: dict, team_id: int) -> tuple[dict, str | None]:
    """Identity of the GitHub user who merged the PR, resolved to a PostHog user when possible.

    Merging is the one unambiguous personal act in the loop, so when the merger's GitHub
    login maps to an org member the pr_merged event attributes to them. Without a match the
    event keeps the task's assigned user (an auto-resolved reviewer or fallback for
    auto-started reports), so a consumer tells the two apart by the presence of
    pr_merged_by_distinct_id.
    """
    merged_by = (payload.get("pull_request") or {}).get("merged_by") or {}
    login = merged_by.get("login")
    if not login:
        return {}, None
    properties: dict = {"pr_merged_by_login": login, "pr_merged_by_id": merged_by.get("id")}
    distinct_id = _resolve_github_login_distinct_id(login, team_id)
    if distinct_id is not None:
        properties["pr_merged_by_distinct_id"] = distinct_id
    return properties, distinct_id
