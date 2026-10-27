import uuid
import datetime as dt

import time_machine
from posthog.test.base import APIBaseTest
from unittest.mock import patch

from django.db import connection
from django.test.utils import CaptureQueriesContext
from django.utils import timezone

from parameterized import parameterized
from rest_framework import status

from posthog.models.personal_api_key import PersonalAPIKey, hash_key_value
from posthog.models.scoping import team_scope
from posthog.models.team import Team
from posthog.models.utils import generate_random_token_personal

from products.aeo.backend.models import AEOCitationCheck, AEOPrompt, AEOPromptVersion
from products.aeo.backend.test.factories import create_citation_check


class TestAEOPromptAPI(APIBaseTest):
    def setUp(self) -> None:
        super().setUp()
        flag_patcher = patch(
            "products.aeo.backend.presentation.views.posthog_feature_flag_enabled",
            return_value=True,
        )
        self.feature_enabled = flag_patcher.start()
        self.addCleanup(flag_patcher.stop)
        self.url = f"/api/projects/{self.team.id}/aeo_prompts/"

    def _record_check(
        self,
        prompt_id: str,
        engine: str,
        *,
        minutes_ago: int,
        cited: bool = False,
        check_failed: bool = False,
        answer_text: str | None = None,
    ) -> str:
        with team_scope(self.team.pk):
            prompt = AEOPrompt.objects.get(id=prompt_id)
            check = AEOCitationCheck.objects.create(
                team=self.team,
                prompt=prompt,
                run_id=uuid.uuid4(),
                prompt_text=prompt.prompt,
                prompt_source=prompt.prompt_source,
                prompt_hash=prompt.prompt_hash,
                prompt_version=prompt.current_version,
                engine=engine,
                model=engine,
                cited=cited,
                check_failed=check_failed,
                answer_text=answer_text,
            )
            AEOCitationCheck.objects.filter(id=check.id).update(
                created_at=timezone.now() - dt.timedelta(minutes=minutes_ago)
            )
        return str(check.id)

    def _import_one_prompt(self) -> str:
        self.client.post(f"{self.url}bulk_import/", {"prompts": [{"prompt": "tracked?"}]}, format="json")
        return self.client.get(self.url).json()["results"][0]["id"]

    def test_requires_the_rollout_flag(self) -> None:
        self.feature_enabled.return_value = False

        assert self.client.get(self.url).status_code == status.HTTP_403_FORBIDDEN
        response = self.client.post(f"{self.url}bulk_import/", {"prompts": [{"prompt": "q?"}]}, format="json")
        assert response.status_code == status.HTTP_403_FORBIDDEN
        assert not AEOPrompt.objects.for_team(self.team.id).exists()

    def test_bulk_import_then_deactivate_survives_a_reimport(self) -> None:
        payload = {
            "prompts": [
                {"prompt": "Best session replay tool?", "topic": "Session replay", "external_visibility": 42.5},
                {"prompt": "Best feature flag tool?", "topic": "Feature flags"},
                {"prompt": "   "},
            ]
        }
        response = self.client.post(f"{self.url}bulk_import/", payload, format="json")
        assert response.status_code == status.HTTP_200_OK, response.json()
        assert response.json() == {"created": 2, "updated": 0, "skipped": 1}

        listed = {row["prompt"]: row for row in self.client.get(self.url).json()["results"]}
        assert listed["Best session replay tool?"]["topic"] == "Session replay"
        assert listed["Best session replay tool?"]["external_visibility"] == 42.5
        assert listed["Best feature flag tool?"]["external_visibility"] is None

        replay_id = listed["Best session replay tool?"]["id"]
        response = self.client.patch(f"{self.url}{replay_id}/", {"active": False}, format="json")
        assert response.status_code == status.HTTP_200_OK
        assert response.json()["active"] is False

        response = self.client.post(f"{self.url}bulk_import/", payload, format="json")
        assert response.json() == {"created": 0, "updated": 2, "skipped": 1}
        assert AEOPrompt.objects.for_team(self.team.id).get(id=replay_id).active is False

        flags_id = listed["Best feature flag tool?"]["id"]
        self.client.delete(f"{self.url}{flags_id}/")
        response = self.client.post(f"{self.url}bulk_import/", payload, format="json")
        assert response.json() == {"created": 0, "updated": 1, "skipped": 2}
        flags = AEOPrompt.objects.for_team(self.team.id).get(id=flags_id)
        assert (flags.archived_at is not None, flags.active) == (True, False)
        assert AEOPrompt.objects.for_team(self.team.id).count() == 2

    def test_text_edit_adds_a_version_and_current_version_rolls_it_back(self) -> None:
        prompt_id = self._import_one_prompt()
        self._record_check(prompt_id, "exa-answer", minutes_ago=30)

        response = self.client.patch(
            f"{self.url}{prompt_id}/",
            {"prompt": "  Still   tracked? ", "version_description": "Clearer wording", "topic": "New topic"},
            format="json",
        )

        assert response.status_code == status.HTTP_200_OK, response.json()
        edited = response.json()
        assert (edited["id"], edited["prompt"], edited["topic"]) == (prompt_id, "Still tracked?", "New topic")
        assert (edited["current_version"], edited["version_count"], len(edited["latest_checks"])) == (2, 2, 1)
        self._record_check(prompt_id, "exa-answer", minutes_ago=5)
        versions = self.client.get(f"{self.url}{prompt_id}/versions/").json()
        assert [(v["version"], v["text"], v["version_description"], v["is_current"]) for v in versions] == [
            (2, "Still tracked?", "Clearer wording", True),
            (1, "tracked?", "", False),
        ]
        assert versions[0]["created_by"]["email"] == self.user.email
        with team_scope(self.team.pk):
            AEOCitationCheck.objects.filter(prompt_id=prompt_id, prompt_version=1).update(prompt_version=None)
        checks = self.client.get(f"{self.url}{prompt_id}/checks/?version=1").json()["results"]
        assert [check["prompt_version"] for check in checks] == [None]

        response = self.client.patch(f"{self.url}{prompt_id}/", {"current_version": 1}, format="json")

        assert response.status_code == status.HTTP_200_OK, response.json()
        rolled_back = response.json()
        assert (rolled_back["prompt"], rolled_back["current_version"], rolled_back["version_count"]) == (
            "tracked?",
            1,
            2,
        )
        assert AEOPromptVersion.objects.for_team(self.team.id).count() == 2

    def test_import_matches_prompts_on_their_current_text(self) -> None:
        prompt_id = self._import_one_prompt()
        self.client.patch(f"{self.url}{prompt_id}/", {"prompt": "Still tracked?"}, format="json")

        response = self.client.post(
            f"{self.url}bulk_import/",
            {"prompts": [{"prompt": "still TRACKED?", "topic": "Kept"}, {"prompt": "tracked?"}]},
            format="json",
        )

        assert response.json() == {"created": 1, "updated": 1, "skipped": 0}
        edited = self.client.get(f"{self.url}{prompt_id}/").json()
        assert (edited["prompt"], edited["topic"], edited["current_version"]) == ("Still tracked?", "Kept", 2)
        assert {row["prompt"]: row["version_count"] for row in self.client.get(self.url).json()["results"]} == {
            "Still tracked?": 2,
            "tracked?": 1,
        }

    @parameterized.expand(
        [
            ("topic_only", {"topic": "Replay"}, "Replay"),
            ("clear_topic", {"topic": ""}, ""),
            ("case_and_whitespace_only", {"prompt": "  TRACKED?  ", "topic": "Replay"}, "Replay"),
            ("current_version_already_current", {"current_version": 1}, "Before"),
        ]
    )
    def test_edits_that_keep_the_text_add_no_version(self, _name: str, body: dict, expected_topic: str) -> None:
        prompt_id = self._import_one_prompt()
        self.client.patch(f"{self.url}{prompt_id}/", {"topic": "Before"}, format="json")

        response = self.client.patch(f"{self.url}{prompt_id}/", body, format="json")

        assert response.status_code == status.HTTP_200_OK, response.json()
        row = response.json()
        assert (row["prompt"], row["topic"], row["current_version"], row["version_count"]) == (
            "tracked?",
            expected_topic,
            1,
            1,
        )

    @parameterized.expand(
        [
            ("text_of_an_active_prompt", False, False),
            ("text_of_an_archived_prompt", True, False),
            ("rollback_onto_an_active_prompt", False, True),
        ]
    )
    def test_taking_another_prompts_text_conflicts(self, _name: str, archive_other: bool, rollback: bool) -> None:
        self.client.post(
            f"{self.url}bulk_import/", {"prompts": [{"prompt": "first?"}, {"prompt": "second?"}]}, format="json"
        )
        ids = {row["prompt"]: row["id"] for row in self.client.get(self.url).json()["results"]}
        if rollback:
            self.client.patch(f"{self.url}{ids['first?']}/", {"prompt": "third?"}, format="json")
            self.client.patch(f"{self.url}{ids['second?']}/", {"prompt": "first?"}, format="json")
            body: dict = {"current_version": 1}
        else:
            body = {"prompt": "SECOND?"}
        if archive_other:
            self.client.delete(f"{self.url}{ids['second?']}/")
        before = AEOPrompt.objects.for_team(self.team.id).get(id=ids["first?"])

        response = self.client.patch(f"{self.url}{ids['first?']}/", body, format="json")

        assert response.status_code == status.HTTP_409_CONFLICT, response.json()
        after = AEOPrompt.objects.for_team(self.team.id).get(id=ids["first?"])
        assert (after.prompt, after.current_version) == (before.prompt, before.current_version)
        assert AEOPromptVersion.objects.for_team(self.team.id).filter(prompt_id=after.id).count() == (
            2 if rollback else 1
        )

    @parameterized.expand(
        [
            ("patch", "patch", {"archived": True}, status.HTTP_200_OK),
            ("delete", "delete", None, status.HTTP_204_NO_CONTENT),
        ]
    )
    def test_archive_hides_the_prompt_from_the_default_list(
        self, _name: str, method: str, body: dict | None, expected_status: int
    ) -> None:
        prompt_id = self._import_one_prompt()
        self._record_check(prompt_id, "exa-answer", minutes_ago=5)

        response = getattr(self.client, method)(f"{self.url}{prompt_id}/", body, format="json")

        assert response.status_code == expected_status
        assert self.client.get(self.url).json()["count"] == 0
        assert self.client.get(f"{self.url}topics/").json() == []
        listed = self.client.get(f"{self.url}?include_archived=true").json()["results"]
        assert [row["id"] for row in listed] == [prompt_id]
        retrieved = self.client.get(f"{self.url}{prompt_id}/").json()
        assert (retrieved["active"], retrieved["archived_at"] is not None) == (False, True)
        assert AEOCitationCheck.objects.for_team(self.team.id).filter(prompt_id=prompt_id).count() == 1

    @parameterized.expand([("stays_off", {}, False), ("turned_on", {"active": True}, True)])
    def test_restore_leaves_the_prompt_off_unless_asked(self, _name: str, extra: dict, expected_active: bool) -> None:
        prompt_id = self._import_one_prompt()
        self.client.delete(f"{self.url}{prompt_id}/")

        response = self.client.patch(f"{self.url}{prompt_id}/", {"archived": False, **extra}, format="json")

        assert response.status_code == status.HTTP_200_OK, response.json()
        assert (response.json()["archived_at"], response.json()["active"]) == (None, expected_active)

    @parameterized.expand(
        [
            ("empty_body", False, {}),
            ("empty_text", False, {"prompt": "   "}),
            ("unknown_version", False, {"current_version": 5}),
            ("text_and_version", False, {"prompt": "new text?", "current_version": 1}),
            ("note_without_text", False, {"version_description": "why"}),
            ("archive_with_other_changes", False, {"archived": True, "topic": "x"}),
            ("toggle_archived", True, {"active": True}),
            ("retopic_archived", True, {"topic": "x"}),
            ("reword_archived", True, {"prompt": "new text?"}),
            ("restore_and_reword", True, {"archived": False, "prompt": "new text?"}),
            ("restore_and_roll_back", True, {"archived": False, "current_version": 1}),
        ]
    )
    def test_rejected_edits_change_nothing(self, _name: str, archive_first: bool, body: dict) -> None:
        prompt_id = self._import_one_prompt()
        if archive_first:
            self.client.delete(f"{self.url}{prompt_id}/")
        before = AEOPrompt.objects.for_team(self.team.id).get(id=prompt_id)

        response = self.client.patch(f"{self.url}{prompt_id}/", body, format="json")

        assert response.status_code == status.HTTP_400_BAD_REQUEST, response.json()
        after = AEOPrompt.objects.for_team(self.team.id).get()
        assert (after.id, after.prompt, after.topic, after.active, after.archived_at, after.current_version) == (
            before.id,
            before.prompt,
            before.topic,
            before.active,
            before.archived_at,
            before.current_version,
        )
        assert AEOPromptVersion.objects.for_team(self.team.id).count() == 1

    @parameterized.expand(
        [
            ("no_filter", "", 6, None),
            ("one_topic", "&topic=same topic", 5, ("topic", "same topic")),
            ("no_topic", "&topic=", 1, ("topic", "")),
            ("active", "&active=true", 5, ("active", True)),
            ("inactive", "&active=false", 1, ("active", False)),
        ]
    )
    def test_list_pages_without_overlap(
        self, _name: str, filters: str, expected: int, field_value: tuple[str, object] | None
    ) -> None:
        prompts = [{"prompt": f"q{i}?", "topic": "same topic"} for i in range(5)] + [{"prompt": "untopiced?"}]
        self.client.post(f"{self.url}bulk_import/", {"prompts": prompts}, format="json")
        untopiced = next(row for row in self.client.get(self.url).json()["results"] if row["topic"] == "")
        self.client.patch(f"{self.url}{untopiced['id']}/", {"active": False}, format="json")

        first = self.client.get(f"{self.url}?limit=3{filters}").json()
        second = self.client.get(f"{self.url}?limit=3&offset=3{filters}").json()

        assert first["count"] == expected
        ids = [row["id"] for row in first["results"] + second["results"]]
        assert len(ids) == len(set(ids)) == expected
        if field_value is not None:
            field, value = field_value
            assert {row[field] for row in first["results"] + second["results"]} == {value}

    def test_topics_lists_each_topic_with_its_prompt_count(self) -> None:
        prompts = [{"prompt": "a?", "topic": "Replay"}, {"prompt": "b?", "topic": "Replay"}, {"prompt": "c?"}]
        self.client.post(f"{self.url}bulk_import/", {"prompts": prompts}, format="json")

        response = self.client.get(f"{self.url}topics/")

        assert response.status_code == status.HTTP_200_OK, response.json()
        assert response.json() == [{"topic": "", "prompts": 1}, {"topic": "Replay", "prompts": 2}]

    def test_list_returns_the_latest_check_per_engine(self) -> None:
        prompts = [{"prompt": "checked?", "topic": "a"}, {"prompt": "never checked?", "topic": "b"}]
        self.client.post(f"{self.url}bulk_import/", {"prompts": prompts}, format="json")
        ids = {row["prompt"]: row["id"] for row in self.client.get(self.url).json()["results"]}
        checked_id = ids["checked?"]
        self._record_check(checked_id, "exa-answer", minutes_ago=60, cited=True)
        self._record_check(checked_id, "exa-answer", minutes_ago=5, cited=False)
        self._record_check(checked_id, "claude-web-search", minutes_ago=90, check_failed=True)
        self._record_check(checked_id, "claude-web-search", minutes_ago=30, cited=True)

        listed = {row["prompt"]: row for row in self.client.get(self.url).json()["results"]}
        retrieved = self.client.get(f"{self.url}{checked_id}/").json()

        for row in (listed["checked?"], retrieved):
            latest = {check["engine"]: check for check in row["latest_checks"]}
            assert len(row["latest_checks"]) == 2
            assert (latest["exa-answer"]["cited"], latest["exa-answer"]["check_failed"]) == (False, False)
            assert (latest["claude-web-search"]["cited"], latest["claude-web-search"]["check_failed"]) == (True, False)
        assert listed["never checked?"]["latest_checks"] == []

    def test_list_query_count_does_not_grow_with_page_size(self) -> None:
        prompts = [{"prompt": f"q{i}?"} for i in range(4)]
        self.client.post(f"{self.url}bulk_import/", {"prompts": prompts}, format="json")
        for row in self.client.get(self.url).json()["results"]:
            self._record_check(row["id"], "exa-answer", minutes_ago=1)
            self._record_check(row["id"], "claude-web-search", minutes_ago=1)

        with CaptureQueriesContext(connection) as one_prompt:
            self.client.get(f"{self.url}?limit=1")
        with CaptureQueriesContext(connection) as four_prompts:
            self.client.get(f"{self.url}?limit=4")

        assert len(four_prompts.captured_queries) == len(one_prompt.captured_queries)

    @parameterized.expand([("all_engines", "", ["c", "b", "a"]), ("one_engine", "&engine=exa-answer", ["c", "a"])])
    def test_checks_list_history_newest_first_in_pages(self, _name: str, filters: str, expected: list[str]) -> None:
        prompt_id = self._import_one_prompt()
        self._record_check(prompt_id, "exa-answer", minutes_ago=30, answer_text="a")
        self._record_check(prompt_id, "claude-web-search", minutes_ago=20, answer_text="b")
        self._record_check(prompt_id, "exa-answer", minutes_ago=10, answer_text="c\nwith a line break")

        first = self.client.get(f"{self.url}{prompt_id}/checks/?limit=2{filters}").json()
        second = self.client.get(f"{self.url}{prompt_id}/checks/?limit=2&offset=2{filters}").json()

        assert first["count"] == len(expected)
        answers = [row["answer_text"] for row in first["results"] + second["results"]]
        assert [answer.split("\n")[0] for answer in answers] == expected
        assert answers[0] == "c\nwith a line break"

    @parameterized.expand([("default", "", 20), ("capped", "?limit=1000", 100)])
    def test_checks_page_size_is_bounded(self, _name: str, query: str, expected: int) -> None:
        prompt_id = self._import_one_prompt()
        with team_scope(self.team.pk):
            prompt = AEOPrompt.objects.get(id=prompt_id)
            AEOCitationCheck.objects.bulk_create(
                AEOCitationCheck(
                    team=self.team,
                    prompt=prompt,
                    run_id=uuid.uuid4(),
                    prompt_text=prompt.prompt,
                    prompt_source=prompt.prompt_source,
                    prompt_hash=prompt.prompt_hash,
                    prompt_version=prompt.current_version,
                    engine="exa-answer",
                    model="exa-answer",
                )
                for _ in range(101)
            )

        response = self.client.get(f"{self.url}{prompt_id}/checks/{query}").json()

        assert response["count"] == 101
        assert len(response["results"]) == expected

    @parameterized.expand(
        [
            ("checks", "get", "checks/", None),
            ("stats", "get", "stats/", None),
            ("versions", "get", "versions/", None),
            ("update", "patch", "", {"prompt": "taken over?"}),
            ("archive", "delete", "", None),
        ]
    )
    def test_another_teams_prompt_is_not_found(self, _name: str, method: str, suffix: str, body: dict | None) -> None:
        other_team = Team.objects.create(organization=self.organization, name="Other")
        other_check_id = create_citation_check(other_team, "other")
        with team_scope(other_team.pk):
            other_prompt_id = AEOCitationCheck.objects.get(id=other_check_id).prompt_id

        response = getattr(self.client, method)(f"{self.url}{other_prompt_id}/{suffix}", body, format="json")

        assert response.status_code == status.HTTP_404_NOT_FOUND
        with team_scope(other_team.pk):
            other_prompt = AEOPrompt.objects.get(id=other_prompt_id)
            assert (other_prompt.prompt, other_prompt.archived_at) == ("is other cited?", None)
            assert AEOPrompt.objects.count() == 1

    @time_machine.travel("2026-10-20T12:00:00Z", tick=False)
    def test_stats_count_checks_per_engine_and_per_day(self) -> None:
        prompt_id = self._import_one_prompt()
        day = 24 * 60
        self._record_check(prompt_id, "exa-answer", minutes_ago=10, cited=True)
        self._record_check(prompt_id, "exa-answer", minutes_ago=20)
        self._record_check(prompt_id, "exa-answer", minutes_ago=day, check_failed=True)
        self._record_check(prompt_id, "claude-web-search", minutes_ago=2 * day, cited=True)
        self._record_check(prompt_id, "claude-web-search", minutes_ago=40 * day)

        response = self.client.get(f"{self.url}{prompt_id}/stats/")

        assert response.status_code == status.HTTP_200_OK, response.json()
        stats = response.json()
        assert stats["total_checks"] == 5
        assert (stats["daily_from"], stats["daily_to"]) == ("2026-09-21", "2026-10-20")
        engines = {
            row["engine"]: (row["checks"], row["cited"], row["failed"], row["citation_rate"])
            for row in stats["engines"]
        }
        assert engines == {"claude-web-search": (2, 1, 0, 0.5), "exa-answer": (3, 1, 1, 0.5)}
        assert [(row["date"], row["engine"], row["checks"], row["cited"], row["failed"]) for row in stats["daily"]] == [
            ("2026-10-18", "claude-web-search", 1, 1, 0),
            ("2026-10-19", "exa-answer", 1, 0, 1),
            ("2026-10-20", "exa-answer", 2, 1, 0),
        ]

    @parameterized.expand([("above_range", 140), ("not_a_number", "NaN"), ("infinite", "Infinity")])
    def test_bulk_import_rejects_invalid_visibility(self, _name: str, visibility: object) -> None:
        response = self.client.post(
            f"{self.url}bulk_import/",
            {"prompts": [{"prompt": "q?", "external_visibility": visibility}]},
            format="json",
        )

        assert response.status_code == status.HTTP_400_BAD_REQUEST
        assert not AEOPrompt.objects.for_team(self.team.id).exists()

    @parameterized.expand(
        [
            ("write_scope", ["web_analytics:write"], status.HTTP_200_OK),
            ("read_scope_only", ["web_analytics:read"], status.HTTP_403_FORBIDDEN),
        ]
    )
    def test_bulk_import_with_a_personal_api_key(self, _name: str, scopes: list[str], expected: int) -> None:
        # Session auth skips scope checks, so only a scoped key catches a custom action left out of the write actions.
        value = generate_random_token_personal()
        PersonalAPIKey.objects.create(
            user=self.user, label="aeo import", secure_value=hash_key_value(value), scopes=scopes
        )
        self.client.logout()

        response = self.client.post(
            f"{self.url}bulk_import/",
            {"prompts": [{"prompt": "Best session replay tool?"}]},
            format="json",
            headers={"authorization": f"Bearer {value}"},
        )

        assert response.status_code == expected, response.json()
