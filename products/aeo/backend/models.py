from django.db import models

from posthog.models.scoping.root_mixin import TeamScopedRootMixin
from posthog.models.utils import CreatedMetaFields, UpdatedMetaFields, UUIDTModel


class AEOPrompt(TeamScopedRootMixin, CreatedMetaFields, UpdatedMetaFields, UUIDTModel):
    """
    One candidate question we run against answer engines to check whether the
    team's domain gets cited (AEO citation-tracking POC).

    Prompts are entered by hand as a control set or imported from a CSV. The
    runner executes every active prompt
    against each configured engine and captures one `$aeo_citation_check`
    event per prompt x engine — the citation record itself lives in events,
    not in Postgres.
    """

    class Source(models.TextChoices):
        # Imported from a CSV (e.g. an existing AEO tool's prompt export).
        IMPORTED = "imported", "Imported"
        # Hand-written control set.
        MANUAL = "manual", "Manual"

    # related_name="+" on both core relations: nothing outside this product may
    # traverse into AEO prompts from a Team or User. db_constraint=False keeps the
    # migration off the locks on posthog_team and posthog_user: creating an FK
    # constraint blocks writes on tables read on nearly every request, so the
    # relations are enforced in the ORM instead.
    team = models.ForeignKey("posthog.Team", on_delete=models.CASCADE, related_name="+", db_constraint=False)
    created_by = models.ForeignKey(
        "posthog.User", on_delete=models.SET_NULL, null=True, blank=True, related_name="+", db_constraint=False
    )

    prompt = models.TextField(help_text="The question to ask the answer engines, as a user would phrase it.")
    prompt_hash = models.CharField(
        max_length=64,
        help_text="SHA-256 of the normalized prompt text; dedupe key and the stable join key on citation-check events.",
    )
    prompt_source = models.CharField(
        max_length=32,
        choices=Source.choices,
        help_text="Where this prompt came from.",
    )
    evidence = models.JSONField(
        default=dict,
        blank=True,
        help_text="Why this prompt made the set (for a CSV import, the file it came from).",
    )
    rank = models.FloatField(default=0, help_text="Seeding score; higher runs first when the set is truncated.")
    active = models.BooleanField(default=True, help_text="Only active prompts are executed by the runner.")

    class Meta:
        db_table = "posthog_aeo_prompt"
        constraints = [
            models.UniqueConstraint(fields=["team", "prompt_hash"], name="aeo_prompt_unique_team_hash"),
        ]
        indexes = [
            models.Index(fields=["team_id", "active"], name="aeo_prompt_team_active_idx"),
        ]

    def __str__(self) -> str:
        return f"[{self.prompt_source}] {self.prompt[:60]}"
