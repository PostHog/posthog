"""
Gateway — a team's named bucket for first-party LLM gateway access (RFC #1103).

A gateway's slug is the product its credentials attribute to: it equals the
$ai_gateway_slug property the Go gateway sets at auth. Many keys can bind to one
gateway. Slugs are validated lowercase/URL-safe on write — the gateway validates
none of it and the slug flows straight onto the billing ledger (ai-gateway #79/#80).
"""

from django.core.validators import RegexValidator
from django.db import models

from posthog.models.scoping.root_mixin import TeamScopedRootMixin
from posthog.models.utils import CreatedMetaFields, UpdatedMetaFields, UUIDModel

# Auto-provisioned per team; teams rename or add more. Sharing across teams is
# fine — attribution is keyed (team_id, slug).
DEFAULT_GATEWAY_SLUG = "default"

# Lowercase, URL-safe, no leading/trailing separator (posthog_code, slack_app, wizard).
GATEWAY_SLUG_PATTERN = r"^[a-z0-9]+(?:[_-][a-z0-9]+)*$"

validate_gateway_slug = RegexValidator(
    regex=GATEWAY_SLUG_PATTERN,
    message="Gateway slug must be lowercase and URL-safe (letters, digits, '-' or '_', no leading/trailing separator).",
)


class Gateway(TeamScopedRootMixin, UUIDModel, CreatedMetaFields, UpdatedMetaFields):  # type: ignore[django-manager-missing]
    team = models.ForeignKey("posthog.Team", on_delete=models.CASCADE, related_name="gateways")
    slug = models.CharField(max_length=64, validators=[validate_gateway_slug])
    is_default = models.BooleanField(default=False)

    # `objects` (from TeamScopedRootMixin) is fail-closed and what app code uses.
    # Framework internals (admin widgets, reverse FK accessors, DRF) read
    # `_default_manager`, which must not fail closed — point it at this unscoped
    # sibling, like ProductTeamModel.
    all_teams = models.Manager()  # noqa: DJ012 — both are managers, ruff misclassifies this

    class Meta:
        default_manager_name = "all_teams"
        constraints = [
            models.UniqueConstraint(fields=["team", "slug"], name="unique_gateway_slug_per_team"),
            models.UniqueConstraint(
                fields=["team"],
                condition=models.Q(is_default=True),
                name="unique_default_gateway_per_team",
            ),
        ]

    def __str__(self) -> str:
        return f"{self.slug} (team {self.team_id})"

    def save(self, *args: object, **kwargs: object) -> None:
        # save() doesn't run field validators; enforce the slug invariant here so
        # no malformed slug reaches the DB (and the billing ledger).
        self.slug = (self.slug or "").strip()
        validate_gateway_slug(self.slug)
        super().save(*args, **kwargs)
