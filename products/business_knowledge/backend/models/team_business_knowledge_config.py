from django.db import models

from posthog.models.team import Team


class TeamBusinessKnowledgeConfig(models.Model):
    """Per-team Business knowledge settings. Lives on a Team extension so posthog_team is never ALTERed."""

    # db_constraint=False: a real FK constraint takes SHARE ROW EXCLUSIVE on posthog_team while
    # migrating, stalling writes under traffic.
    team = models.OneToOneField(Team, on_delete=models.CASCADE, primary_key=True, db_constraint=False, related_name="+")

    learn_from_support_enabled = models.BooleanField(
        default=False,
        db_default=False,
        help_text=(
            "When true, PostHog learns reusable knowledge from public human replies on resolved "
            "support tickets. Requires Support to be enabled for this environment."
        ),
    )
    # Environment-scoped, unlike learn_from_support_enabled. A GitHub App installation belongs to
    # this environment, so a child environment must not inherit the parent's repository allowlist.
    github_integration_id = models.IntegerField(
        null=True,
        blank=True,
        help_text="GitHub integration id for this environment. Null when GitHub is not connected.",
    )
    github_repos = models.JSONField(
        default=list,
        db_default=[],
        blank=True,
        help_text="Lowercased owner/repo names this environment allows business knowledge to read.",
    )

    class Meta:
        app_label = "business_knowledge"
