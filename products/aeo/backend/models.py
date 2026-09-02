from django.db import models

from posthog.models.scoping.root_mixin import TeamScopedRootMixin
from posthog.models.utils import CreatedMetaFields, UpdatedMetaFields, UUIDTModel


class AEOPrompt(TeamScopedRootMixin, CreatedMetaFields, UpdatedMetaFields, UUIDTModel):
    """
    One candidate question we run against answer engines to check whether the
    team's domain gets cited (AEO citation-tracking POC).

    Prompts are seeded from first-party data (user-reported signup prompts,
    AI-channel landing pages, AI-agent-crawled content, search queries) or
    entered by hand as a control set. The runner executes every active prompt
    against each configured engine and captures one `$aeo_citation_check`
    event per prompt x engine — the citation record itself lives in events,
    not in Postgres.
    """

    class Source(models.TextChoices):
        # Free-text prompts users reported at signup ("what prompt led you here").
        USER_REPORTED = "user_reported", "User reported"
        # Derived from pages where AI-channel sessions land.
        AI_ENTRY_PAGE = "ai_entry_page", "AI entry page"
        # Derived from content paths AI agents crawl.
        CRAWLED_CONTENT = "crawled_content", "Crawled content"
        # Derived from search-console query data.
        GSC_QUERY = "gsc_query", "Search console query"
        # Imported from a CSV (e.g. an existing AEO tool's prompt export).
        IMPORTED = "imported", "Imported"
        # Hand-written control set, the baseline first-party seeding must beat.
        MANUAL = "manual", "Manual"

    team = models.ForeignKey("posthog.Team", on_delete=models.CASCADE)

    prompt = models.TextField(help_text="The question to ask the answer engines, as a user would phrase it.")
    prompt_hash = models.CharField(
        max_length=64,
        help_text="SHA-256 of the normalized prompt text; dedupe key and the stable join key on citation-check events.",
    )
    prompt_source = models.CharField(
        max_length=32,
        choices=Source.choices,
        help_text="Where this prompt came from — the seeded-vs-manual comparison is the POC's main experiment.",
    )
    evidence = models.JSONField(
        default=dict,
        blank=True,
        help_text="Why this prompt made the set (signup counts, entry paths, crawl counts, query clicks).",
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
