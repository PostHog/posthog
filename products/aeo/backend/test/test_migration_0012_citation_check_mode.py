import uuid
from typing import Any

from posthog.test.base import NonAtomicTestMigrations


class TestCitationCheckMode(NonAtomicTestMigrations):
    app = "aeo"
    migrate_from = "0011_keyword"
    migrate_to = "0012_citation_check_mode"

    def setUpBeforeMigration(self, apps: Any) -> None:
        AEOPrompt = apps.get_model("aeo", "AEOPrompt")
        AEOCitationCheck = apps.get_model("aeo", "AEOCitationCheck")
        prompt = AEOPrompt.objects.create(team_id=self.team.id, prompt="q?", prompt_hash="q", prompt_source="manual")
        self.check_id = AEOCitationCheck.objects.create(
            team_id=self.team.id,
            prompt=prompt,
            run_id=uuid.uuid4(),
            prompt_text="q?",
            prompt_source="manual",
            prompt_hash="q",
            engine="claude-web-search",
            model="claude",
        ).id

    def test_existing_checks_read_as_web_search_with_no_config(self) -> None:
        AEOCitationCheck = self.apps.get_model("aeo", "AEOCitationCheck")  # type: ignore[union-attr]

        assert AEOCitationCheck.objects.filter(id=self.check_id).values_list("mode", "mode_config").get() == (
            "web_search",
            {},
        )
