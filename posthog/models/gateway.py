"""
Gateway — a team's named bucket for first-party LLM gateway access (RFC #1103).

A gateway's slug is the product its credentials attribute to: it equals the
$ai_gateway_slug property the Go gateway sets at auth. Many keys can bind to one
gateway. Slugs are validated lowercase/URL-safe on write — the gateway validates
none of it and the slug flows straight onto the billing ledger (ai-gateway #79/#80).
"""

from django.core.validators import MaxLengthValidator, RegexValidator
from django.db import models

from posthog.models.scoping.root_mixin import TeamScopedRootMixin
from posthog.models.utils import CreatedMetaFields, UpdatedMetaFields, UUIDModel

# Slug of the gateway auto-provisioned for every team. It's an ordinary gateway
# with no special status — teams rename, delete, or add more. There is no
# fallback attribution: a credential must name a gateway or it has no policy.
DEFAULT_GATEWAY_SLUG = "default"

# Lowercase, URL-safe, no leading/trailing separator (posthog_code, slack_app, wizard).
GATEWAY_SLUG_PATTERN = r"^[a-z0-9]+(?:[_-][a-z0-9]+)*$"
GATEWAY_SLUG_MAX_LENGTH = 64

validate_gateway_slug = RegexValidator(
    regex=GATEWAY_SLUG_PATTERN,
    message="Gateway slug must be lowercase and URL-safe (letters, digits, '-' or '_', no leading/trailing separator).",
)
validate_gateway_slug_length = MaxLengthValidator(GATEWAY_SLUG_MAX_LENGTH)


class Gateway(TeamScopedRootMixin, UUIDModel, CreatedMetaFields, UpdatedMetaFields):
    team = models.ForeignKey("posthog.Team", on_delete=models.CASCADE, related_name="gateways")
    slug = models.CharField(max_length=GATEWAY_SLUG_MAX_LENGTH, validators=[validate_gateway_slug])

    # `objects` (from TeamScopedRootMixin) is fail-closed and what app code uses.
    # Framework internals (admin widgets, reverse FK accessors, DRF) read
    # `_default_manager`, which must not fail closed — point it at this unscoped
    # sibling, like ProductTeamModel.
    all_teams = models.Manager()  # noqa: DJ012 — both are managers, ruff misclassifies this

    class Meta:
        default_manager_name = "all_teams"
        constraints = [
            models.UniqueConstraint(fields=["team", "slug"], name="unique_gateway_slug_per_team"),
            # save() validates, but bulk_create/queryset.update/raw SQL bypass it. The
            # slug lands on the billing ledger, so enforce the invariant at the DB too.
            models.CheckConstraint(condition=models.Q(slug__regex=GATEWAY_SLUG_PATTERN), name="gateway_slug_url_safe"),
        ]

    def __str__(self) -> str:
        return f"{self.slug} (team {self.team_id})"

    def save(self, *args: object, **kwargs: object) -> None:
        # save() doesn't run field validators; enforce the slug invariant here so
        # no malformed slug reaches the DB (and the billing ledger).
        self.slug = (self.slug or "").strip()
        validate_gateway_slug(self.slug)
        validate_gateway_slug_length(self.slug)
        super().save(*args, **kwargs)
