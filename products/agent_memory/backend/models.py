from django.db import models

from posthog.models.scoping.root_mixin import TeamScopedRootMixin
from posthog.models.utils import UUIDModel


class AgentMemoryFile(TeamScopedRootMixin, UUIDModel):
    """A single markdown file in a team's shared agent-memory tree.

    Source of truth for the bytes is object storage (`agent_memory/{team_id}/{path}`);
    this row is a Postgres-side index + cached copy so listing and reads don't fan out
    to S3 on every call, and so optimistic concurrency (compare-and-set on `version`)
    has a transactional anchor.

    Concurrency: every mutation bumps `version` monotonically. Writers pass the
    `version` they last read; if it no longer matches, the write is rejected with a
    conflict and the caller must re-read and merge. See `ARCHITECTURE.md` for why this
    beats last-write-wins for a fleet of agents editing the same tree.
    """

    team = models.ForeignKey("posthog.Team", on_delete=models.CASCADE, related_name="agent_memory_files")
    # Relative path within the team's tree, e.g. "project.md", "users/jane-doe.md",
    # "scouts/signals-scout-errors/scratchpad.md". Normalized (no leading slash, no
    # "..") before it ever reaches the DB or object storage — see logic.normalize_path.
    path = models.CharField(max_length=1024)
    # Cached copy of the markdown body. Object storage is the source of truth, but
    # reads/listing serve from here to avoid an S3 round-trip per call.
    content = models.TextField(default="", blank=True)
    # Monotonic per-file version, the compare-and-set token. Starts at 1 on create,
    # +1 on every successful write.
    version = models.PositiveIntegerField(default=1)
    # Who last wrote the file. Nullable: agent runs may have no human author.
    updated_by = models.ForeignKey(
        "posthog.User",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="+",
    )
    # Free-form identifier of the agent run that last wrote the file (e.g. a scout run
    # UUID, a Slack thread ts). Plain string so any agent surface can attribute a write
    # without a cross-product FK.
    updated_by_run = models.CharField(max_length=255, null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "Agent memory file"
        verbose_name_plural = "Agent memory files"
        constraints = [
            # Doubles as the lookup index for (team, path) — the primary read path.
            models.UniqueConstraint(fields=["team", "path"], name="agent_memory_file_unique_team_path"),
        ]

    def __str__(self) -> str:
        return f"{self.team_id}:{self.path}@v{self.version}"
