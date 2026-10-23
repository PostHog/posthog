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

from products.aeo.backend.models import AEOCitationCheck, AEOPrompt
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
        response = self.client.patch(f"{self.url}{replay_id}/", {"active": False, "topic": "ignored"}, format="json")
        assert response.status_code == status.HTTP_200_OK
        assert response.json()["active"] is False
        assert response.json()["topic"] == "Session replay"

        response = self.client.post(f"{self.url}bulk_import/", payload, format="json")
        assert response.json() == {"created": 0, "updated": 2, "skipped": 1}
        assert AEOPrompt.objects.for_team(self.team.id).get(id=replay_id).active is False

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
                    engine="exa-answer",
                    model="exa-answer",
                )
                for _ in range(101)
            )

        response = self.client.get(f"{self.url}{prompt_id}/checks/{query}").json()

        assert response["count"] == 101
        assert len(response["results"]) == expected

    @parameterized.expand([("checks", "checks/"), ("stats", "stats/")])
    def test_another_teams_prompt_is_not_found(self, _name: str, suffix: str) -> None:
        other_team = Team.objects.create(organization=self.organization, name="Other")
        other_check_id = create_citation_check(other_team, "other")
        with team_scope(other_team.pk):
            other_prompt_id = AEOCitationCheck.objects.get(id=other_check_id).prompt_id

        response = self.client.get(f"{self.url}{other_prompt_id}/{suffix}")

        assert response.status_code == status.HTTP_404_NOT_FOUND

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
