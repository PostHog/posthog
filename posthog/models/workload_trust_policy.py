from __future__ import annotations

from collections.abc import Iterable
from datetime import datetime, timedelta
from typing import Any

from django.conf import settings
from django.contrib.postgres.fields import ArrayField
from django.db import models, transaction
from django.utils import timezone

from posthog.models.activity_logging.model_activity import ModelActivityMixin
from posthog.models.scoping.root_mixin import TeamScopedRootMixin
from posthog.models.utils import UUIDModel
from posthog.scopes import UNPRIVILEGED_SCOPES
from posthog.utils import safe_cache_delete

# A policy can grant any unprivileged scope except the ones that let a workload token outlive itself or
# widen its own access. Risky scopes that stay grantable carry a warning from `RISKY_SCOPE_WARNINGS`.
# - `workload_trust_policy` and `workload_trust_policy_request` would let a workload change the policy behind its token.
# - `task:write` starts an agent run from a prompt the caller writes, with its own longer-lived owner token.
#   `conversation:write` (PostHog AI can create such a task), `signal_scout:write`,
#   `business_knowledge:write`, `autoresearch:write` and `hog_flow:write` (a workflow can create a task) start the
#   same kind of run.
# - `conversation:read` and `task:read` read the owner's private PostHog AI chats and tasks, because the token
#   acts as the owner. Add them back if a workload needs them.
# - `project:write` lets a token rotate the project's secret token.
# - `user:write` changes the account of the owner the token acts as.
# - `streamlit_app` returns a one-hour OAuth token to connect to a running app.
# - `webhook:write`, `batch_export:write` and `subscription:write` set up feeds that keep sending after the
#   policy is revoked. A subscription can send to any email address.
# - `sharing_configuration` creates and reveals public sharing links, which keep working after the policy is revoked.
WORKLOAD_TRUST_POLICY_DENIED_SCOPES: frozenset[str] = frozenset(
    {
        "workload_trust_policy:read",
        "workload_trust_policy:write",
        "workload_trust_policy_request:read",
        "workload_trust_policy_request:write",
        "autoresearch:write",
        "batch_export:write",
        "business_knowledge:write",
        "conversation:read",
        "conversation:write",
        "hog_flow:write",
        "project:write",
        "sharing_configuration:read",
        "sharing_configuration:write",
        "signal_scout:write",
        "streamlit_app:read",
        "streamlit_app:write",
        "subscription:write",
        "task:read",
        "task:write",
        "user:write",
        "webhook:write",
    }
)


# A policy's issuer, subject and conditions form one entry of the unique btree index below, which Postgres caps
# at about 2.7 kB. With the 255-character issuer and subject, these limits keep the largest entry well below it.
CONDITION_VALUE_MAX_LENGTH = 200
CONDITIONS_MAX_BYTES = 1024


def workload_trust_policy_grantable_scopes() -> frozenset[str]:
    return UNPRIVILEGED_SCOPES - WORKLOAD_TRUST_POLICY_DENIED_SCOPES


def workload_trust_policy_scopes_not_grantable(scopes: Iterable[str]) -> list[str]:
    grantable = workload_trust_policy_grantable_scopes()
    return sorted({scope for scope in scopes if scope not in grantable})


def workload_trust_policies_settings_url(team_id: int) -> str:
    return f"{settings.SITE_URL}/project/{team_id}/settings/environment-trusted-workloads"


def workload_trust_policy_request_url(team_id: int, request_id: str) -> str:
    return f"{settings.SITE_URL}/project/{team_id}/workload-trust-policy-requests/{request_id}"


def workload_trust_policy_version(policy: WorkloadTrustPolicy) -> str:
    """Changes on every save, so a token minted before an admin narrowed or disabled the policy stops
    matching it."""
    return str(int(policy.updated_at.timestamp() * 1_000_000))


def workload_trust_policy_active_cache_key(policy_id: str) -> str:
    return f"workload_trust_policy_active:{policy_id}"


class WorkloadTrustPolicy(ModelActivityMixin, TeamScopedRootMixin, UUIDModel):
    """Lets a workload, such as a CI job, exchange its OIDC token for a short-lived project token. Azure
    calls this a federated identity credential, AWS a role trust policy, Google Cloud a workload identity
    provider, and PyPI and npm trusted publishing.

    The shape follows the common OIDC model: issuer, subject, claim conditions. A policy always pins the
    subject by its immutable claim and by its name. Every key in `conditions` is a claim the token must
    carry with exactly that value, and an empty map adds no conditions.
    """

    activity_logging_on_delete = True

    # No standalone index: the unique constraint below leads on team_id.
    team = models.ForeignKey("posthog.Team", on_delete=models.CASCADE, db_constraint=False, db_index=False)
    name = models.CharField(max_length=200)
    issuer = models.CharField(max_length=255)
    subject_name = models.CharField(max_length=255)
    subject = models.CharField(max_length=255)
    # Claim name to required value. Write it only through `normalize_workload_conditions`, which drops empty
    # values, so two policies with the same conditions always collide in the constraint.
    conditions = models.JSONField(default=dict, blank=True)
    scopes = ArrayField(models.CharField(max_length=100), default=list)
    enabled = models.BooleanField(default=True)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, db_constraint=False
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        constraints = [
            # jsonb equality ignores key order, so the constraint compares conditions by content.
            models.UniqueConstraint(
                fields=["team", "issuer", "subject", "conditions"],
                name="posthog_unique_workload_trust_policy_conditions",
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
        # Workload token authentication caches whether a policy is active. Dropping the entry after the commit
        # makes a disable or delete take effect on the next request rather than when the entry expires.
        key = workload_trust_policy_active_cache_key(policy_id or str(self.pk))
        transaction.on_commit(lambda: safe_cache_delete(key))

    def __str__(self) -> str:
        return f"WorkloadTrustPolicy(team={self.team_id}, name={self.name!r})"


WORKLOAD_TRUST_POLICY_REQUEST_LIFETIME = timedelta(hours=24)


def _default_request_expiry() -> datetime:
    return timezone.now() + WORKLOAD_TRUST_POLICY_REQUEST_LIFETIME


class WorkloadTrustPolicyRequest(ModelActivityMixin, TeamScopedRootMixin, UUIDModel):
    """A member's request for a workload trust policy. It grants nothing until an organization admin or owner
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
    subject_name = models.CharField(max_length=255)
    subject = models.CharField(max_length=255)
    # Normalized like `WorkloadTrustPolicy.conditions`, so approving copies it unchanged.
    conditions = models.JSONField(default=dict, blank=True)
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
    # The OAuth app the request came through, so the approval page names it and shows whether PostHog
    # verified it. Null when the request came through another credential.
    requested_via_application = models.ForeignKey(
        "posthog.OAuthApplication",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        db_constraint=False,
        related_name="+",
    )
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
    policy = models.ForeignKey(WorkloadTrustPolicy, on_delete=models.SET_NULL, null=True, blank=True, related_name="+")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        indexes = [models.Index(fields=["team", "status", "-created_at"], name="posthog_workload_req_team_idx")]

    @property
    def effective_status(self) -> str:
        if self.status == self.Status.PENDING and timezone.now() >= self.expires_at:
            return self.Status.EXPIRED
        return self.status

    def __str__(self) -> str:
        return (
            f"WorkloadTrustPolicyRequest(team={self.team_id}, subject_name={self.subject_name!r}, status={self.status})"
        )
