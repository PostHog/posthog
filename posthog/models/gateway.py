"""
Gateway — a team's named binding for first-party LLM gateway access (RFC #1103).

Each gateway is bound to exactly one first-party credential (a phx_ personal key
or a pha_ OAuth application; see the OneToOne fields on those models). The
gateway's slug is the product the credential's traffic attributes to: it equals
the $ai_gateway_slug event property the Go gateway sets at auth, so internal
billing stays continuous. One gateway → one key → one slug; there is no per-call
selector.

Slugs are validated lowercase/URL-safe on write because the Go gateway does no
validation of its own — it passes gateway_slug straight onto the billing ledger
and the $ai_gateway_slug property (ai-gateway #79/#80). Django is the sole
validator, so a malformed slug must never be persisted.
"""

from django.core.validators import RegexValidator
from django.db import models

from posthog.models.scoping.root_mixin import TeamScopedRootMixin
from posthog.models.utils import CreatedMetaFields, UpdatedMetaFields, UUIDModel

# Every team is auto-provisioned a gateway with this slug; teams rename it (or add
# more) to map onto their $ai_gateway_slug. Sharing "default" across teams is fine:
# attribution is keyed (team_id, gateway_slug), so team_id disambiguates.
DEFAULT_GATEWAY_SLUG = "default"

# Lowercase, URL-safe, no leading/trailing separator (posthog_code, slack_app, wizard).
GATEWAY_SLUG_PATTERN = r"^[a-z0-9]+(?:[_-][a-z0-9]+)*$"

validate_gateway_slug = RegexValidator(
    regex=GATEWAY_SLUG_PATTERN,
    message="Gateway slug must be lowercase and URL-safe (letters, digits, '-' or '_', no leading/trailing separator).",
)


class Gateway(TeamScopedRootMixin, UUIDModel, CreatedMetaFields, UpdatedMetaFields):
    team = models.ForeignKey("posthog.Team", on_delete=models.CASCADE, related_name="gateways")
    slug = models.CharField(max_length=64, validators=[validate_gateway_slug])
    is_default = models.BooleanField(default=False)

    # `objects` (fail-closed TeamScopedManager) comes from TeamScopedRootMixin and is
    # what app code reaches for. Django framework internals (admin form widgets, the
    # reverse O2O accessors on PersonalAPIKey/OAuthApplication, prefetch_related, DRF
    # default querysets) read through `_default_manager`, which must not fail closed —
    # point it at this unscoped sibling, mirroring ProductTeamModel.
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
        # Field validators only run via full_clean(), which save() doesn't call.
        # Enforce the slug invariant here so no malformed slug can reach the DB
        # (and the gateway's billing ledger) through any write path.
        self.slug = (self.slug or "").strip()
        validate_gateway_slug(self.slug)
        super().save(*args, **kwargs)
