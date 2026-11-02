from __future__ import annotations

from collections.abc import Iterable

from django.conf import settings
from django.contrib.postgres.fields import ArrayField
from django.db import models

from posthog.models.activity_logging.model_activity import ModelActivityMixin
from posthog.models.scoping.root_mixin import TeamScopedRootMixin
from posthog.models.utils import UUIDModel
from posthog.scopes import UNPRIVILEGED_SCOPES

# A policy can grant any unprivileged scope except the ones that let a CI token outlive itself or widen
# its own access. Risky scopes that stay grantable carry a warning from `RISKY_SCOPE_WARNINGS`.
# - `ci_trust_policy` would let a CI job change the policy behind its token.
# - `task:write` starts an agent run from a prompt the caller writes, with its own longer-lived owner token.
#   `conversation:write` (PostHog AI can create such a task), `signal_scout:write` and
#   `business_knowledge:write` start the same kind of run.
# - `project:write` lets a token rotate the project's secret token.
# - `streamlit_app` returns a one-hour OAuth token to connect to a running app.
CI_TRUST_POLICY_DENIED_SCOPES: frozenset[str] = frozenset(
    {
        "ci_trust_policy:read",
        "ci_trust_policy:write",
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

    def __str__(self) -> str:
        return f"CITrustPolicy(team={self.team_id}, name={self.name!r})"
