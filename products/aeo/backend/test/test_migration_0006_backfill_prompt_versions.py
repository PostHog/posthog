import datetime as dt
from typing import Any

from posthog.test.base import TestMigrations


class TestBackfillPromptVersions(TestMigrations):
    app = "aeo"
    migrate_from = "0005_prompt_versions_and_archive"
    migrate_to = "0006_backfill_prompt_versions"

    def setUpBeforeMigration(self, apps: Any) -> None:
        AEOPrompt = apps.get_model("aeo", "AEOPrompt")
        self.created_at = dt.datetime(2026, 1, 2, tzinfo=dt.UTC)
        self.prompt_ids = []
        for text in ("first?", "second?"):
            prompt = AEOPrompt.objects.create(
                team_id=self.team.id, prompt=text, prompt_hash=text, prompt_source="imported"
            )
            AEOPrompt.objects.filter(id=prompt.id).update(created_at=self.created_at)
            self.prompt_ids.append(prompt.id)

    def test_every_prompt_gets_version_one_from_its_text(self) -> None:
        AEOPromptVersion = self.apps.get_model("aeo", "AEOPromptVersion")  # type: ignore[union-attr]
        AEOPrompt = self.apps.get_model("aeo", "AEOPrompt")  # type: ignore[union-attr]

        versions = AEOPromptVersion.objects.order_by("text").values_list("prompt_id", "version", "text", "created_at")

        assert list(versions) == [
            (self.prompt_ids[0], 1, "first?", self.created_at),
            (self.prompt_ids[1], 1, "second?", self.created_at),
        ]
        assert set(AEOPrompt.objects.values_list("current_version", flat=True)) == {1}
