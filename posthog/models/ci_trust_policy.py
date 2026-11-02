from __future__ import annotations

from collections.abc import Iterable
from datetime import datetime, timedelta
from typing import Any

from django.conf import settings
from django.contrib.postgres.fields import ArrayField
from django.core.cache import cache
from django.db import models, transaction
from django.utils import timezone

from posthog.models.activity_logging.model_activity import ModelActivityMixin
from posthog.models.scoping.root_mixin import TeamScopedRootMixin
from posthog.models.utils import UUIDModel
from posthog.scopes import UNPRIVILEGED_SCOPES

# A policy can grant any unprivileged scope except the ones that let a CI token outlive itself or widen
# its own access. Risky scopes that stay grantable carry a warning from `RISKY_SCOPE_WARNINGS`.
# - `ci_trust_policy` and `ci_trust_policy_request` would let a CI job change the policy behind its token.
# - `task:write` starts an agent run from a prompt the caller writes, with its own longer-lived owner token.
#   `conversation:write` (PostHog AI can create such a task), `signal_scout:write` and
#   `business_knowledge:write` start the same kind of run.
# - `project:write` lets a token rotate the project's secret token.
# - `streamlit_app` returns a one-hour OAuth token to connect to a running app.
CI_TRUST_POLICY_DENIED_SCOPES: frozenset[str] = frozenset(
    {
        "ci_trust_policy:read",
        "ci_trust_policy:write",
        "ci_trust_policy_request:read",
        "ci_trust_policy_request:write",
        "business_knowledge:write",
        "conversation:write",
        "project:write",
        "signal_scout:write",
        "streamlit_app:read",
        "streamlit_app:write",
        "task:write",
    }
)


def ci_trust_policy_grantable_scopes() -> frozenset[str]:
    return UNPRIVILEGED_SCOPES - CI_TRUST_POLICY_DENIED_SCOPES


def ci_trust_policy_scopes_not_grantable(scopes: Iterable[str]) -> list[str]:
    grantable = ci_trust_policy_grantable_scopes()
    return sorted({scope for scope in scopes if scope not in grantable})


def ci_trust_policies_settings_url(team_id: int) -> str:
    return f"{settings.SITE_URL}/project/{team_id}/settings/environment-ci-trust-policies"


def ci_trust_policy_request_url(team_id: int, request_id: str) -> str:
    return f"{settings.SITE_URL}/project/{team_id}/ci-trust-policy-requests/{request_id}"


def ci_trust_policy_version(policy: CITrustPolicy) -> str:
    """Changes on every save, so a token minted before an admin narrowed or disabled the policy stops
    matching it."""
    return str(int(policy.updated_at.timestamp() * 1_000_000))


def ci_trust_policy_active_cache_key(policy_id: str) -> str:
    return f"ci_trust_policy_active:{policy_id}"


class CITrustPolicy(ModelActivityMixin, TeamScopedRootMixin, UUIDModel):
    """Lets CI jobs of one repository exchange their OIDC token for a short-lived project token.

    An empty `ref` or `environment` matches any value. The repository is always pinned, by name and
    by its immutable id.
    """

    activity_logging_on_delete = True

    # No standalone index: the unique constraint below leads on team_id.
    team = models.ForeignKey("posthog.Team", on_delete=models.CASCADE, db_constraint=False, db_index=False)
    name = models.CharField(max_length=200)
    issuer = models.CharField(max_length=255)
    repository = models.CharField(max_length=255)
    repository_id = models.CharField(max_length=100)
    ref = models.CharField(max_length=255, blank=True, default="")
    environment = models.CharField(max_length=255, blank=True, default="")
    scopes = ArrayField(models.CharField(max_length=100), default=list)
    enabled = models.BooleanField(default=True)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, db_constraint=False
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["team", "issuer", "repository_id", "ref", "environment"],
                name="posthog_unique_ci_trust_policy_conditions",
            ),
        ]

    def save(self, *args: Any, **kwargs: Any) -> None:
        super().save(*args, **kwargs)
        self._forget_active_state()

    def delete(self, *args: Any, **kwargs: Any) -> tuple[int, dict[str, int]]:
        policy_id = str(self.pk)
        result = super().delete(*args, **kwargs)
        self._forget_active_state(policy_id)
        return result

    def _forget_active_state(self, policy_id: str | None = None) -> None:
        # CI token authentication caches whether a policy is active. Dropping the entry after the commit
        # makes a disable or delete take effect on the next request rather than when the entry expires.
        key = ci_trust_policy_active_cache_key(policy_id or str(self.pk))
        transaction.on_commit(lambda: cache.delete(key))

    def __str__(self) -> str:
        return f"CITrustPolicy(team={self.team_id}, name={self.name!r})"


CI_TRUST_POLICY_REQUEST_LIFETIME = timedelta(days=7)


def _default_request_expiry() -> datetime:
    return timezone.now() + CI_TRUST_POLICY_REQUEST_LIFETIME


class CITrustPolicyRequest(ModelActivityMixin, TeamScopedRootMixin, UUIDModel):
    """A member's request for a CI trust policy. It grants nothing until an organization admin or owner
    approves it in the browser, which creates the policy.

    The requested conditions never change after creation, so the admin approves exactly what they saw.
    """

    class Status(models.TextChoices):
        PENDING = "pending", "Pending"
        APPROVED = "approved", "Approved"
        REJECTED = "rejected", "Rejected"
        EXPIRED = "expired", "Expired"

    team = models.ForeignKey("posthog.Team", on_delete=models.CASCADE, db_constraint=False, db_index=False)
    name = models.CharField(max_length=200)
    issuer = models.CharField(max_length=255)
    repository = models.CharField(max_length=255)
    repository_id = models.CharField(max_length=100)
    ref = models.CharField(max_length=255, blank=True, default="")
    environment = models.CharField(max_length=255, blank=True, default="")
    scopes = ArrayField(models.CharField(max_length=100), default=list)
    # Never stored as `expired`: a pending request past `expires_at` reads as expired through `effective_status`.
    status = models.CharField(max_length=16, choices=Status.choices, default=Status.PENDING)
    requested_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        db_constraint=False,
        related_name="+",
    )
    # The client the request came through, for example the OAuth application's name, so the approval page
    # can say "requested through hog".
    requested_via = models.CharField(max_length=255, blank=True, default="")
    # Null when the request did not come through an OAuth app.
    requested_via_verified = models.BooleanField(null=True, blank=True)
    expires_at = models.DateTimeField(default=_default_request_expiry)
    resolved_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        db_constraint=False,
        related_name="+",
    )
    resolved_at = models.DateTimeField(null=True, blank=True)
    policy = models.ForeignKey(CITrustPolicy, on_delete=models.SET_NULL, null=True, blank=True, related_name="+")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        indexes = [models.Index(fields=["team", "status", "-created_at"], name="posthog_ci_policy_req_team_idx")]

    @property
    def effective_status(self) -> str:
        if self.status == self.Status.PENDING and timezone.now() >= self.expires_at:
            return self.Status.EXPIRED
        return self.status

    def __str__(self) -> str:
        return f"CITrustPolicyRequest(team={self.team_id}, repository={self.repository!r}, status={self.status})"
