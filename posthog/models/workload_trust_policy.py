from __future__ import annotations

from collections.abc import Iterable

from django.conf import settings
from django.contrib.postgres.fields import ArrayField
from django.db import models

from posthog.models.activity_logging.model_activity import ModelActivityMixin
from posthog.models.scoping.root_mixin import TeamScopedRootMixin
from posthog.models.utils import UUIDModel
from posthog.scopes import UNPRIVILEGED_SCOPES

# A policy can grant any unprivileged scope except the ones that let a workload token outlive itself or
# widen its own access. Risky scopes that stay grantable carry a warning from `RISKY_SCOPE_WARNINGS`.
# - `workload_trust_policy` would let a workload change the policy behind its token.
# - `task:write` starts an agent run from a prompt the caller writes, with its own longer-lived owner token.
#   `conversation:write` (PostHog AI can create such a task), `signal_scout:write` and
#   `business_knowledge:write` start the same kind of run.
# - `conversation:read` and `task:read` read the owner's private PostHog AI chats and tasks, because the token
#   acts as the owner. Add them back if a workload needs them.
# - `project:write` lets a token rotate the project's secret token.
# - `streamlit_app` returns a one-hour OAuth token to connect to a running app.
# - `webhook:write`, `batch_export:write` and `subscription:write` set up feeds that keep sending after the
#   policy is revoked. A subscription can send to any email address.
# - `sharing_configuration` creates and reveals public sharing links, which keep working after the policy is revoked.
WORKLOAD_TRUST_POLICY_DENIED_SCOPES: frozenset[str] = frozenset(
    {
        "workload_trust_policy:read",
        "workload_trust_policy:write",
        "batch_export:write",
        "business_knowledge:write",
        "conversation:read",
        "conversation:write",
        "project:write",
        "sharing_configuration:read",
        "sharing_configuration:write",
        "signal_scout:write",
        "streamlit_app:read",
        "streamlit_app:write",
        "subscription:write",
        "task:read",
        "task:write",
        "webhook:write",
    }
)


def workload_trust_policy_grantable_scopes() -> frozenset[str]:
    return UNPRIVILEGED_SCOPES - WORKLOAD_TRUST_POLICY_DENIED_SCOPES


def workload_trust_policy_scopes_not_grantable(scopes: Iterable[str]) -> list[str]:
    grantable = workload_trust_policy_grantable_scopes()
    return sorted({scope for scope in scopes if scope not in grantable})


def workload_trust_policies_settings_url(team_id: int) -> str:
    return f"{settings.SITE_URL}/project/{team_id}/settings/environment-trusted-workloads"


class WorkloadTrustPolicy(ModelActivityMixin, TeamScopedRootMixin, UUIDModel):
    """Lets a workload, such as the CI jobs of one repository, exchange its OIDC token for a short-lived
    project token. Azure calls this a federated identity credential, AWS a role trust policy, Google
    Cloud a workload identity provider, and PyPI and npm trusted publishing.

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
                name="posthog_unique_workload_trust_policy_conditions",
            ),
        ]

    def __str__(self) -> str:
        return f"WorkloadTrustPolicy(team={self.team_id}, name={self.name!r})"
