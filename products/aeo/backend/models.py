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


class AEOCitationCheck(TeamScopedRootMixin, CreatedMetaFields, UUIDTModel):
    """
    One prompt run against one answer engine, and whether the team's domain was
    cited (AEO citation-tracking POC).

    The runner writes these rows; nothing else does. That is the point: the
    citation record is read through `system.aeo_citation_checks` in HogQL, so
    insights, the SQL editor, the API, and MCP can all read it, while the only
    write path is the backend runner. Storing it as events would have made every
    row forgeable by anyone holding the project's public capture token.

    Prompt text and source are denormalized so a check keeps the question that
    actually ran, even after the prompt set changes.
    """

    # db_constraint=False on the core relations, for the same reason as AEOPrompt.
    team = models.ForeignKey("posthog.Team", on_delete=models.CASCADE, related_name="+", db_constraint=False)
    created_by = models.ForeignKey(
        "posthog.User", on_delete=models.SET_NULL, null=True, blank=True, related_name="+", db_constraint=False
    )
    prompt = models.ForeignKey(AEOPrompt, on_delete=models.CASCADE, related_name="checks")

    run_id = models.UUIDField(help_text="Groups every check captured by one runner pass.")
    prompt_text = models.TextField(help_text="The question as it ran, snapshotted from the prompt set.")
    prompt_source = models.CharField(max_length=32, help_text="Prompt source at the time of the run.")
    prompt_hash = models.CharField(max_length=64, help_text="SHA-256 of the normalized prompt text.")

    engine = models.CharField(
        max_length=64, help_text="Answer engine: claude-web-search, openai-web-search, exa-answer."
    )
    model = models.CharField(max_length=128, help_text="Engine model that answered.")

    check_failed = models.BooleanField(
        default=False,
        help_text="The engine did not answer. Kept so a reader can tell 'the engine broke' from 'the citations disappeared'.",
    )
    error = models.TextField(null=True, blank=True, help_text="Why the check failed, when it did.")

    cited = models.BooleanField(default=False, help_text="A target-domain URL appears in the answer's citations.")
    num_citations = models.IntegerField(default=0, help_text="How many URLs the answer cited.")
    target_best_position = models.IntegerField(
        null=True, blank=True, help_text="1-based position of the first target-domain URL in the citation list."
    )

    cited_urls = models.JSONField(default=list, blank=True, help_text="URLs the answer cites, in first-mention order.")
    retrieved_urls = models.JSONField(
        default=list, blank=True, help_text="URLs the engine retrieved but did not necessarily cite."
    )
    search_queries = models.JSONField(default=list, blank=True, help_text="Search queries the engine issued.")
    target_urls = models.JSONField(default=list, blank=True, help_text="Cited URLs on a target domain.")
    top_cited_domains = models.JSONField(default=list, blank=True, help_text="Distinct hosts across the cited URLs.")

    cost_usd = models.FloatField(null=True, blank=True, help_text="Engine-reported cost, where the engine reports one.")
    gateway_trace_id = models.CharField(
        max_length=64,
        null=True,
        blank=True,
        help_text="Joins to the gateway's $ai_generation event, which carries token and web-search cost.",
    )

    class Meta:
        db_table = "posthog_aeo_citation_check"
        indexes = [
            models.Index(fields=["team_id", "created_at"], name="aeo_check_team_created_idx"),
            models.Index(fields=["team_id", "engine"], name="aeo_check_team_engine_idx"),
        ]

    def __str__(self) -> str:
        return f"[{self.engine}] cited={self.cited} {self.prompt_text[:40]}"
