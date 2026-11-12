import json
import uuid
import datetime as dt
from types import SimpleNamespace

import pytest
import time_machine
from posthog.test.base import APIBaseTest
from unittest.mock import MagicMock, patch

from django.conf import settings
from django.core.cache import cache
from django.db import connection
from django.test.utils import CaptureQueriesContext
from django.utils import timezone

import requests
from parameterized import parameterized
from rest_framework import status
from temporalio.common import WorkflowIDConflictPolicy

from posthog.models.personal_api_key import PersonalAPIKey, hash_key_value
from posthog.models.scoping import team_scope
from posthog.models.team import Team
from posthog.models.utils import generate_random_token_personal
from posthog.rate_limit import AEOKeywordReportBurstRateThrottle
from posthog.redis import get_client

from products.aeo.backend.engine_settings import engine_schedule
from products.aeo.backend.engines import top_domains
from products.aeo.backend.facade.api import RECOMPUTE_DEBOUNCE_SECONDS, create_keywords, get_prompt_set_overview
from products.aeo.backend.models import AEOBrand, AEOCitationCheck, AEOKeyword, AEOPrompt, AEOPromptVersion
from products.aeo.backend.test.factories import create_citation_check, create_own_brand


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
        position: int | None = None,
        check_failed: bool = False,
        answer_text: str | None = None,
        cited_urls: list[str] | None = None,
        search_queries: list[str] | None = None,
        mode: str = "web_search",
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
                prompt_topic=prompt.topic,
                prompt_version=prompt.current_version,
                engine=engine,
                model=engine,
                mode=mode,
                cited=cited,
                target_best_position=position,
                check_failed=check_failed,
                answer_text=answer_text,
                cited_urls=cited_urls or [],
                top_cited_domains=top_domains(cited_urls or []),
                search_queries=search_queries or [],
            )
            AEOCitationCheck.objects.filter(id=check.id).update(
                created_at=timezone.now() - dt.timedelta(minutes=minutes_ago)
            )
        return str(check.id)

    def _import_one_prompt(self) -> str:
        self.client.post(f"{self.url}bulk_import/", {"prompts": [{"prompt": "tracked?"}]}, format="json")
        return self.client.get(self.url).json()["results"][0]["id"]

    def _import_prompts(self, prompts: list[dict]) -> dict[str, str]:
        self.client.post(f"{self.url}bulk_import/", {"prompts": prompts}, format="json")
        listed = self.client.get(f"{self.url}?limit=100").json()["results"]
        return {row["prompt"]: row["id"] for row in listed}

    def test_requires_the_rollout_flag(self) -> None:
        self.feature_enabled.return_value = False

        assert self.client.get(self.url).status_code == status.HTTP_403_FORBIDDEN
        response = self.client.post(f"{self.url}bulk_import/", {"prompts": [{"prompt": "q?"}]}, format="json")
        assert response.status_code == status.HTTP_403_FORBIDDEN
        assert not AEOPrompt.objects.for_team(self.team.id).exists()
        assert self.client.get(f"/api/projects/{self.team.id}/aeo_brands/").status_code == status.HTTP_403_FORBIDDEN

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

        self.client.post(
            f"{self.url}bulk_import/",
            {"prompts": [{"prompt": "Best session replay tool?", "topic": "Session replay"}]},
            format="json",
        )
        assert self.client.get(f"{self.url}{replay_id}/").json()["external_visibility"] == 42.5

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
        self._record_check(checked_id, "exa-answer", minutes_ago=60, cited=True, search_queries=["older search"])
        self._record_check(
            checked_id, "exa-answer", minutes_ago=5, cited=False, search_queries=["checked 2026", "checked review"]
        )
        self._record_check(checked_id, "claude-web-search", minutes_ago=90, check_failed=True)
        self._record_check(checked_id, "claude-web-search", minutes_ago=30, cited=True, position=2)
        self._record_check(
            checked_id, "claude-no-search", minutes_ago=1, mode="no_search", answer_text="Example, from memory."
        )
        create_own_brand(self.team, "example.com")

        listed = {row["prompt"]: row for row in self.client.get(self.url).json()["results"]}
        retrieved = self.client.get(f"{self.url}{checked_id}/").json()

        for row in (listed["checked?"], retrieved):
            latest = {check["engine"]: check for check in row["latest_checks"]}
            assert len(row["latest_checks"]) == 3
            # A no-search engine never cites, so its column reads the mention instead.
            no_search = latest["claude-no-search"]
            assert (no_search["mode"], no_search["cited"], no_search["mentioned"]) == ("no_search", False, True)
            assert (latest["exa-answer"]["cited"], latest["exa-answer"]["check_failed"]) == (False, False)
            assert (latest["claude-web-search"]["cited"], latest["claude-web-search"]["check_failed"]) == (True, False)
            assert (
                latest["exa-answer"]["target_best_position"],
                latest["claude-web-search"]["target_best_position"],
            ) == (None, 2)
            assert latest["exa-answer"]["search_queries"] == ["checked 2026", "checked review"]
            # An answer with no text reads as not mentioned, never null.
            assert latest["exa-answer"]["mentioned"] is False
            assert latest["claude-web-search"]["search_queries"] == []
        assert listed["never checked?"]["latest_checks"] == []

    def test_list_needs_improvement_keeps_answered_prompts_without_a_recent_citation(self) -> None:
        texts = ["cited?", "never cited?", "only failed?", "cited long ago?", "never checked?"]
        self.client.post(f"{self.url}bulk_import/", {"prompts": [{"prompt": t} for t in texts]}, format="json")
        ids = {row["prompt"]: row["id"] for row in self.client.get(self.url).json()["results"]}
        self._record_check(ids["cited?"], "exa-answer", minutes_ago=10, cited=False)
        self._record_check(ids["cited?"], "claude-web-search", minutes_ago=10, cited=True)
        self._record_check(ids["never cited?"], "exa-answer", minutes_ago=10, cited=False)
        self._record_check(ids["only failed?"], "exa-answer", minutes_ago=10, check_failed=True)
        self._record_check(ids["cited long ago?"], "exa-answer", minutes_ago=60 * 24 * 40, cited=True)
        self._record_check(ids["cited long ago?"], "exa-answer", minutes_ago=10, cited=False)
        self._record_check(ids["never checked?"], "claude-no-search", minutes_ago=10, mode="no_search")
        # A citation on the old wording must not hide a current wording that no engine cites.
        self.client.post(f"{self.url}bulk_import/", {"prompts": [{"prompt": "edited?"}]}, format="json")
        edited_id = next(row["id"] for row in self.client.get(self.url).json()["results"] if row["prompt"] == "edited?")
        self._record_check(edited_id, "exa-answer", minutes_ago=20, cited=True)
        self.client.patch(f"{self.url}{edited_id}/", {"prompt": "edited again?"}, format="json")
        self._record_check(edited_id, "exa-answer", minutes_ago=10, cited=False)

        response = self.client.get(self.url, {"needs_improvement": "true"}).json()

        assert sorted(row["prompt"] for row in response["results"]) == [
            "cited long ago?",
            "edited again?",
            "never cited?",
        ]
        assert response["count"] == 3

    @parameterized.expand(
        [
            (
                "brand_from_a_subdomain_target",
                ["docs.example.com"],
                ["Is EXAMPLE's replay fast?", "how does example.com price replay?", "is example good for funnels?"],
            ),
            ("no_brand", [], []),
        ]
    )
    def test_list_flags_branded_prompts_and_filters_on_them(
        self, _name: str, target_domains: list[str], expected_branded: list[str]
    ) -> None:
        texts = [
            "is example good for funnels?",
            "how does example.com price replay?",
            "Is EXAMPLE's replay fast?",
            "are examples of funnels useful?",
            "counterexample to funnels?",
            "best funnel tools?",
        ]
        self.client.post(f"{self.url}bulk_import/", {"prompts": [{"prompt": t} for t in texts]}, format="json")

        for domain in target_domains:
            create_own_brand(self.team, domain)
        listed = self.client.get(self.url).json()["results"]
        branded = self.client.get(self.url, {"branded": "true"}).json()
        non_branded = self.client.get(self.url, {"branded": "false"}).json()

        assert sorted(row["prompt"] for row in listed if row["branded"]) == expected_branded
        assert sorted(row["prompt"] for row in branded["results"]) == expected_branded
        assert branded["count"] == len(expected_branded)
        assert sorted(row["prompt"] for row in non_branded["results"]) == sorted(set(texts) - set(expected_branded))

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

    @parameterized.expand(
        [
            (
                "since_drops_older_checks",
                "since={since}",
                status.HTTP_200_OK,
                [("exa-answer", "c"), ("claude-web-search", "b")],
            ),
            (
                "without_answer_text",
                "include_answer_text=false",
                status.HTTP_200_OK,
                [("exa-answer", None), ("claude-web-search", None), ("exa-answer", None)],
            ),
            ("invalid_since", "since=yesterday", status.HTTP_400_BAD_REQUEST, None),
        ]
    )
    def test_checks_list_filters_by_date_and_drops_answer_text_on_request(
        self, _name: str, query: str, expected_status: int, expected: list[tuple[str, str | None]] | None
    ) -> None:
        prompt_id = self._import_one_prompt()
        self._record_check(prompt_id, "exa-answer", minutes_ago=30, answer_text="a")
        self._record_check(prompt_id, "claude-web-search", minutes_ago=20, answer_text="b")
        self._record_check(prompt_id, "exa-answer", minutes_ago=10, answer_text="c")
        since = (timezone.now() - dt.timedelta(minutes=25)).strftime("%Y-%m-%dT%H:%M:%SZ")

        response = self.client.get(f"{self.url}{prompt_id}/checks/?{query.format(since=since)}")

        assert response.status_code == expected_status, response.json()
        if expected is not None:
            assert response.json()["count"] == len(expected)
            assert [(row["engine"], row["answer_text"]) for row in response.json()["results"]] == expected

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
        self._record_check(prompt_id, "exa-answer", minutes_ago=10, cited=True, position=1)
        self._record_check(prompt_id, "exa-answer", minutes_ago=20, answer_text="Example Analytics is one option.")
        self._record_check(prompt_id, "exa-answer", minutes_ago=day, check_failed=True)
        self._record_check(prompt_id, "claude-web-search", minutes_ago=2 * day, cited=True, position=3)
        self._record_check(prompt_id, "claude-web-search", minutes_ago=40 * day)
        self._record_check(
            prompt_id, "claude-no-search", minutes_ago=30, mode="no_search", answer_text="Example is a good pick."
        )

        create_own_brand(self.team, "example.com")

        response = self.client.get(f"{self.url}{prompt_id}/stats/")

        assert response.status_code == status.HTTP_200_OK, response.json()
        stats = response.json()
        assert stats["total_checks"] == 6
        assert (stats["daily_from"], stats["daily_to"]) == ("2026-09-21", "2026-10-20")
        engines = {
            row["engine"]: (
                row["checks"],
                row["cited"],
                row["mentioned"],
                row["failed"],
                row["citation_rate"],
                row["mention_rate"],
            )
            for row in stats["engines"]
        }
        assert engines == {
            "claude-no-search": (1, 0, 1, 0, 0.0, 1.0),
            "claude-web-search": (2, 1, 1, 0, 0.5, 0.5),
            "exa-answer": (3, 1, 2, 1, 0.5, 1.0),
        }
        assert [
            (row["date"], row["engine"], row["checks"], row["cited"], row["mentioned"], row["failed"])
            for row in stats["daily"]
        ] == [
            ("2026-10-18", "claude-web-search", 1, 1, 1, 0),
            ("2026-10-19", "exa-answer", 1, 0, 0, 1),
            ("2026-10-20", "claude-no-search", 1, 0, 1, 0),
            ("2026-10-20", "exa-answer", 2, 1, 2, 0),
        ]
        assert {row["engine"]: row["avg_position"] for row in stats["engines"]} == {
            "claude-no-search": None,
            "claude-web-search": 3.0,
            "exa-answer": 1.0,
        }
        assert [row["avg_position"] for row in stats["daily"]] == [3.0, None, None, 1.0]
        assert stats["brand_names"] == ["example"]
        # Consensus and search words read web-search answers only, so the no-search answer adds nothing.
        assert (stats["consensus"], stats["top_words"]) == ([], [])
        assert [(row["engine"], row["unscored"]) for row in stats["sentiment"]] == [
            ("claude-no-search", 1),
            ("claude-web-search", 1),
            ("exa-answer", 2),
        ]

    @parameterized.expand(
        [
            ("brand_named_in_the_answer", {"answer_text": "Try Example Analytics for funnels."}, 1),
            ("brand_case_ignored", {"answer_text": "EXAMPLE ships session replay."}, 1),
            ("brand_inside_another_word", {"answer_text": "Counterexample: nothing fits."}, 0),
            ("cited_without_the_name_in_the_text", {"cited": True, "answer_text": "See [1]."}, 1),
            ("failed_check", {"check_failed": True}, 0),
        ]
    )
    def test_stats_count_a_mention_when_the_answer_names_the_brand(
        self, _name: str, check: dict, expected_mentioned: int
    ) -> None:
        prompt_id = self._import_one_prompt()
        self._record_check(prompt_id, "exa-answer", minutes_ago=10, **check)

        create_own_brand(self.team, "example.com")

        stats = self.client.get(f"{self.url}{prompt_id}/stats/").json()

        assert [row["mentioned"] for row in stats["engines"]] == [expected_mentioned]
        assert [row["mentioned"] for row in stats["daily"]] == [expected_mentioned]

    def test_stats_count_brand_sentiment_per_engine_and_checks_expose_it(self) -> None:
        prompt_id = self._import_one_prompt()
        scored = self._record_check(prompt_id, "exa-answer", minutes_ago=10, answer_text="Example is great.")
        self._record_check(prompt_id, "exa-answer", minutes_ago=20, answer_text="Example is slow.")
        self._record_check(prompt_id, "exa-answer", minutes_ago=30, answer_text="Example exists.")
        self._record_check(prompt_id, "claude-web-search", minutes_ago=40, answer_text="Nothing about the brand.")
        with team_scope(self.team.pk):
            for text, label, score in (("great", "positive", 0.9), ("slow", "negative", 0.7)):
                AEOCitationCheck.objects.filter(answer_text__contains=text).update(
                    brand_sentiment=label, brand_sentiment_score=score
                )

        create_own_brand(self.team, "example.com")

        stats = self.client.get(f"{self.url}{prompt_id}/stats/").json()
        checks = self.client.get(f"{self.url}{prompt_id}/checks/?engine=exa-answer").json()["results"]

        assert [
            (row["engine"], row["positive"], row["neutral"], row["negative"], row["unscored"])
            for row in stats["sentiment"]
        ] == [("claude-web-search", 0, 0, 0, 0), ("exa-answer", 1, 0, 1, 1)]
        assert {check["id"]: (check["brand_sentiment"], check["brand_sentiment_score"]) for check in checks} == {
            scored: ("positive", 0.9),
            **{check["id"]: (check["brand_sentiment"], check["brand_sentiment_score"]) for check in checks[1:]},
        }
        assert [check["brand_sentiment"] for check in checks] == ["positive", "negative", None]

    @time_machine.travel("2026-10-20T12:00:00Z", tick=False)
    def test_stats_rank_engine_consensus_and_search_words_over_the_window(self) -> None:
        prompt_id = self._import_one_prompt()
        day = 24 * 60
        ours = "https://docs.example.com/product-analytics"
        rival = "https://rival.example.org/best-tools"
        self._record_check(
            prompt_id,
            "claude-web-search",
            minutes_ago=10,
            cited=True,
            cited_urls=[rival, ours, "https://rival.example.org/pricing", rival],
            search_queries=["Best product analytics tools", "product analytics for startups"],
        )
        self._record_check(
            prompt_id,
            "claude-web-search",
            minutes_ago=day,
            cited_urls=[rival],
            search_queries=["best product analytics tools"],
        )
        self._record_check(
            prompt_id,
            "openai-web-search",
            minutes_ago=2 * day,
            cited=True,
            cited_urls=["https://community.example.net/thread", ours],
            search_queries=["open source analytics"],
        )
        self._record_check(prompt_id, "exa-answer", minutes_ago=3 * day, cited_urls=[])
        self._record_check(prompt_id, "openai-web-search", minutes_ago=4 * day, check_failed=True)
        self._record_check(prompt_id, "openai-web-search", minutes_ago=40 * day, cited_urls=[rival, rival, rival])

        create_own_brand(self.team, "example.com")

        stats = self.client.get(f"{self.url}{prompt_id}/stats/").json()

        assert [(row["engine"], row["domain"], row["checks_citing"], row["checks"]) for row in stats["consensus"]] == [
            ("claude-web-search", "docs.example.com", 1, 2),
            ("claude-web-search", "rival.example.org", 2, 2),
            ("claude-web-search", "community.example.net", 0, 2),
            ("exa-answer", "docs.example.com", 0, 1),
            ("exa-answer", "rival.example.org", 0, 1),
            ("exa-answer", "community.example.net", 0, 1),
            ("openai-web-search", "docs.example.com", 1, 1),
            ("openai-web-search", "rival.example.org", 0, 1),
            ("openai-web-search", "community.example.net", 1, 1),
        ]
        assert [(row["word"], row["count"]) for row in stats["top_words"]] == [
            ("analytics", 4),
            ("product", 3),
            ("tools", 2),
            ("open", 1),
            ("source", 1),
            ("startups", 1),
        ]

    def test_engine_settings_start_from_defaults_and_drive_the_run_schedule(self) -> None:
        engines_url = f"/api/projects/{self.team.id}/aeo_engines/"
        with patch(
            "products.aeo.backend.engines.resolve_ai_gateway_config",
            return_value=SimpleNamespace(url="https://gw.test/v1", api_key="k"),
        ):
            listed = self.client.get(engines_url).json()
            updated = self.client.patch(
                f"{engines_url}claude-no-search/", {"enabled": True, "frequency": "weekly"}, format="json"
            )
            unknown = self.client.patch(f"{engines_url}not-an-engine/", {"enabled": True}, format="json")
            schedule = engine_schedule(self.team.id)

        defaults = {row["engine"]: (row["mode"], row["enabled"], row["frequency"]) for row in listed}
        assert defaults["claude-web-search"] == ("web_search", True, "daily")
        assert defaults["claude-no-search"] == ("no_search", False, "daily")
        assert updated.status_code == status.HTTP_200_OK, updated.json()
        assert (updated.json()["enabled"], updated.json()["frequency"]) == (True, "weekly")
        assert unknown.status_code == status.HTTP_404_NOT_FOUND
        assert [engine.name for engine in schedule.weekly] == ["claude-no-search"]
        assert "claude-no-search" not in [engine.name for engine in schedule.daily]

    @time_machine.travel("2026-10-20T12:00:00Z", tick=False)
    def test_overview_counts_the_set_per_window_engine_and_topic(self) -> None:
        ids = self._import_prompts(
            [
                {"prompt": "funnels?", "topic": "Analytics"},
                {"prompt": "retention?", "topic": "Analytics"},
                {"prompt": "replay?", "topic": ""},
                {"prompt": "flags?", "topic": "Flags"},
                {"prompt": "surveys?", "topic": "Surveys"},
            ]
        )
        self.client.patch(f"{self.url}{ids['retention?']}/", {"active": False}, format="json")
        self.client.delete(f"{self.url}{ids['flags?']}/")
        day = 24 * 60
        ours = "https://docs.example.com/funnels"
        rival = "https://rival.example.org/funnels"
        self._record_check(
            ids["funnels?"],
            "claude-web-search",
            minutes_ago=10,
            cited=True,
            position=1,
            cited_urls=[ours, rival],
            search_queries=["Funnel  tools", "example funnels"],
        )
        self._record_check(
            ids["funnels?"], "openai-web-search", minutes_ago=10, check_failed=True, search_queries=["funnel tools"]
        )
        self._record_check(
            ids["retention?"],
            "exa-answer",
            minutes_ago=day,
            answer_text="Example has retention.",
            search_queries=["funnel tools", "FUNNEL TOOLS"],
        )
        self._record_check(
            ids["replay?"],
            "claude-web-search",
            minutes_ago=2 * day,
            cited_urls=[rival, rival],
            search_queries=["session replay", " "],
        )
        self._record_check(
            ids["flags?"],
            "exa-answer",
            minutes_ago=3 * day,
            cited=True,
            position=1,
            cited_urls=[ours],
            search_queries=["funnel tools"],
        )
        self._record_check(ids["funnels?"], "claude-web-search", minutes_ago=35 * day, search_queries=["funnel tools"])
        self._record_check(ids["replay?"], "exa-answer", minutes_ago=40 * day, cited=True, position=4)
        self._record_check(ids["funnels?"], "claude-web-search", minutes_ago=70 * day, cited=True)
        # No-search answers never count toward the overview: every number below reads web-search checks only.
        no_search: list[tuple[str, str, int, str | None, bool]] = [
            ("funnels?", "claude-no-search", 20, "Example has funnels.", False),
            ("retention?", "claude-no-search", day, "Example tracks retention.", False),
            ("surveys?", "claude-no-search", day, "Try a survey tool.", False),
            ("surveys?", "claude-no-search", 2 * day, None, True),
            ("funnels?", "openai-no-search", 30, "Example, among others.", False),
            ("replay?", "claude-no-search", 40 * day, "Example records sessions.", False),
        ]
        for prompt, engine, minutes_ago, answer_text, failed in no_search:
            self._record_check(
                ids[prompt],
                engine,
                minutes_ago=minutes_ago,
                answer_text=answer_text,
                check_failed=failed,
                mode="no_search",
            )

        create_own_brand(self.team, "example.com")

        response = self.client.get(f"{self.url}overview/")

        assert response.status_code == status.HTTP_200_OK, response.json()
        overview = response.json()
        assert (overview["days"], overview["window_from"], overview["window_to"]) == (30, "2026-09-21", "2026-10-20")
        assert overview["prompts_tracked"] == 3
        assert (overview["target_domains"], overview["brand_names"]) == (["example.com"], ["example"])
        assert overview["current"] == {
            "checks": 5,
            "failed": 1,
            "cited": 2,
            "mentioned": 3,
            "prompts": 4,
            "prompts_cited": 2,
            "avg_position": 1.0,
            "citation_rate": 0.5,
            "mention_rate": 0.75,
        }
        assert [
            (row["date"], row["engine"], row["checks"], row["cited"], row["mentioned"], row["failed"])
            for row in overview["daily"]
        ] == [
            ("2026-10-17", "exa-answer", 1, 1, 1, 0),
            ("2026-10-18", "claude-web-search", 1, 0, 0, 0),
            ("2026-10-19", "exa-answer", 1, 0, 1, 0),
            ("2026-10-20", "claude-web-search", 1, 1, 1, 0),
            ("2026-10-20", "openai-web-search", 1, 0, 0, 1),
        ]
        assert overview["previous"] == {
            "checks": 2,
            "failed": 0,
            "cited": 1,
            "mentioned": 1,
            "prompts": 2,
            "prompts_cited": 1,
            "avg_position": 4.0,
            "citation_rate": 0.5,
            "mention_rate": 0.5,
        }
        assert [
            (row["engine"], row["checks"], row["failed"], row["cited"], row["mentioned"], row["prompts"])
            for row in overview["engines"]
        ] == [("claude-web-search", 2, 0, 1, 1, 2), ("exa-answer", 2, 0, 1, 2, 2), ("openai-web-search", 1, 1, 0, 0, 1)]
        assert [
            (
                row["topic"],
                row["active_prompts"],
                row["checks"],
                row["failed"],
                row["cited"],
                row["mentioned"],
                row["mention_rate"],
            )
            for row in overview["topics"]
        ] == [
            ("", 1, 1, 0, 0, 0, 0.0),
            ("Analytics", 1, 3, 1, 1, 2, 1.0),
            ("Flags", 0, 1, 0, 1, 1, 1.0),
            ("Surveys", 1, 0, 0, 0, 0, None),
        ]
        assert [
            (row["domain"], row["answers"], row["share_of_answers"], row["is_target"])
            for row in overview["top_domains"]
        ] == [
            ("docs.example.com", 2, 0.5, True),
            ("rival.example.org", 2, 0.5, False),
        ]
        assert [
            (
                row["query"],
                row["prompts"],
                row["answers"],
                row["cited"],
                row["engines"],
                sorted(prompt["text"] for prompt in row["top_prompts"]),
            )
            for row in overview["top_searches"]
        ] == [
            ("funnel tools", 3, 3, 2, ["claude-web-search", "exa-answer"], ["flags?", "funnels?", "retention?"]),
            ("example funnels", 1, 1, 1, ["claude-web-search"], ["funnels?"]),
            ("session replay", 1, 1, 0, ["claude-web-search"], ["replay?"]),
        ]
        child = Team.objects.create(organization=self.organization, name="child env", parent_team=self.team)
        via_child = get_prompt_set_overview(child.id, timezone_name="UTC", days=7)
        assert [domain.domain for domain in via_child.top_domains] == ["docs.example.com", "rival.example.org"]
        assert [search.query for search in via_child.top_searches] == [
            "funnel tools",
            "example funnels",
            "session replay",
        ]

    @time_machine.travel("2026-10-20T12:00:00Z", tick=False)
    def test_rankings_use_the_competitors_confirmed_in_the_catalog(self) -> None:
        ids = self._import_prompts([{"prompt": "funnels?"}])
        with team_scope(self.team.pk):
            AEOBrand.objects.create(
                team=self.team,
                name="Acme",
                domain="acme.co.uk",
                kind="competitor",
                status="confirmed",
                source="manual",
                aliases=["Acme Ltd!"],
            )
            AEOBrand.objects.create(
                team=self.team,
                name="Rival",
                domain="rival.io",
                kind="competitor",
                status="suggested",
                source="citations",
            )
        self._record_check(
            ids["funnels?"],
            "claude-web-search",
            minutes_ago=10,
            answer_text="Acme Ltd! is popular.",
            cited_urls=["https://rival.io/x"],
        )
        self._record_check(ids["funnels?"], "exa-answer", minutes_ago=20, answer_text="Nothing here.")

        create_own_brand(self.team, "example.com")
        rankings = self.client.get(f"{self.url}rankings/").json()

        assert rankings["competitors_confirmed"] is True
        assert [(row["domain"], row["name"], row["answers_mentioning"]) for row in rankings["brands"]] == [
            ("acme.co.uk", "Acme", 1),
            ("example.com", "example", 0),
        ]

    @time_machine.travel("2026-10-20T12:00:00Z", tick=False)
    def test_rankings_fallback_skips_brands_ignored_or_labeled_otherwise(self) -> None:
        ids = self._import_prompts([{"prompt": "funnels?"}])
        with team_scope(self.team.pk):
            AEOBrand.objects.create(
                team=self.team, name="Rival", domain="rival.io", kind="competitor", status="ignored", source="citations"
            )
            AEOBrand.objects.create(
                team=self.team,
                name="Acme",
                domain="acme.co.uk",
                kind="publisher",
                status="confirmed",
                source="citations",
            )
        self._record_check(
            ids["funnels?"],
            "claude-web-search",
            minutes_ago=10,
            answer_text="Rival and Acme.",
            cited_urls=["https://rival.io/x", "https://acme.co.uk/z", "https://third.io/y"],
        )

        create_own_brand(self.team, "example.com")
        rankings = self.client.get(f"{self.url}rankings/").json()

        assert rankings["competitors_confirmed"] is False
        assert [row["domain"] for row in rankings["brands"]] == ["third.io", "example.com"]

    @time_machine.travel("2026-10-20T12:00:00Z", tick=False)
    def test_rankings_compare_the_brand_with_competitors_from_cited_domains(self) -> None:
        ids = self._import_prompts([{"prompt": "funnels?"}, {"prompt": "replay?"}])
        day = 24 * 60
        self._record_check(
            ids["funnels?"],
            "claude-web-search",
            minutes_ago=10,
            cited=True,
            answer_text="Rival is fine.",
            cited_urls=["https://docs.example.com/a", "https://rival.io/x"],
        )
        self._record_check(
            ids["replay?"],
            "exa-answer",
            minutes_ago=day,
            answer_text="Example works well.",
            cited_urls=["https://www.reddit.com/r/a", "https://blog.rival.io/y", "https://www.example.com/pricing"],
        )
        self._record_check(
            ids["funnels?"],
            "openai-web-search",
            minutes_ago=2 * day,
            answer_text="Nothing to see.",
            cited_urls=["https://acme.co.uk/z", "https://example.de/q", "https://[bad/x"],
        )
        self._record_check(
            ids["funnels?"], "openai-web-search", minutes_ago=10, check_failed=True, cited_urls=["https://rival.io/x"]
        )
        self._record_check(ids["replay?"], "claude-web-search", minutes_ago=35 * day, answer_text="Example.")
        self._record_check(ids["replay?"], "claude-web-search", minutes_ago=day, answer_text="Rival.", mode="no_search")
        # Written after the request's snapshot instant, so no count may include it.
        self._record_check(
            ids["replay?"], "exa-answer", minutes_ago=-5, answer_text="Late.", cited_urls=["https://late.example.net/x"]
        )

        create_own_brand(self.team, "docs.example.com")
        response = self.client.get(f"{self.url}rankings/")

        assert response.status_code == status.HTTP_200_OK, response.json()
        rankings = response.json()
        assert (rankings["window_from"], rankings["window_to"], rankings["answers"]) == ("2026-09-21", "2026-10-20", 3)
        assert rankings["competitors_confirmed"] is False
        assert [
            (
                row["domain"],
                row["name"],
                row["is_target"],
                row["answers_mentioning"],
                round(row["visibility"], 3),
                row["previous_visibility"],
            )
            for row in rankings["brands"]
        ] == [
            ("example.com", "example", True, 2, 0.667, 1.0),
            ("rival.io", "rival", False, 2, 0.667, 0.0),
            ("acme.co.uk", "acme", False, 1, 0.333, 0.0),
        ]
        assert [(row["date"], row["visibility"]) for row in rankings["daily"] if row["domain"] == "rival.io"] == [
            ("2026-10-18", 0.0),
            ("2026-10-19", 1.0),
            ("2026-10-20", 1.0),
        ]
        assert [
            (row["domain"], row["answers"], row["urls"], row["is_target"], row["is_competitor"])
            for row in rankings["top_domains"]
        ] == [
            ("example.com", 2, 2, True, False),
            ("rival.io", 2, 2, False, True),
            ("acme.co.uk", 1, 1, False, True),
            ("example.de", 1, 1, False, False),
            ("reddit.com", 1, 1, False, False),
        ]
        assert {row["url"]: row["is_target"] for row in rankings["top_pages"]} == {
            "https://acme.co.uk/z": False,
            "https://blog.rival.io/y": False,
            "https://docs.example.com/a": True,
            "https://example.de/q": False,
            "https://rival.io/x": False,
            "https://www.example.com/pricing": True,
            "https://www.reddit.com/r/a": False,
        }

    @parameterized.expand(
        [
            (
                "all",
                ["example.com"],
                "all",
                (6, 1, 3, 1, 2, 1, 5, 3, 2),
                ["example.com", "rival.example.org"],
                ["example pricing", "funnel tools"],
                (5, ["https://example.com/pricing", "https://rival.example.org/x"]),
            ),
            (
                "branded",
                ["example.com"],
                "branded",
                (3, 0, 2, 1, 1, 1, 3, 3, 2),
                ["example.com"],
                ["example pricing"],
                (3, ["https://example.com/pricing"]),
            ),
            (
                "non_branded",
                ["example.com"],
                "non_branded",
                (3, 1, 1, 0, 1, 0, 2, 3, 2),
                ["rival.example.org"],
                ["funnel tools"],
                (2, ["https://rival.example.org/x"]),
            ),
            ("no_brand_branded", [], "branded", (0, 0, 0, 0, 0, 0, 0, 0, 5), [], [], (0, [])),
            (
                "no_brand_non_branded",
                [],
                "non_branded",
                (6, 1, 1, 1, 2, 0, 5, 0, 5),
                ["example.com", "rival.example.org"],
                ["example pricing", "funnel tools"],
                (5, ["https://example.com/pricing", "https://rival.example.org/x"]),
            ),
        ]
    )
    @time_machine.travel("2026-10-20T12:00:00Z", tick=False)
    def test_overview_and_rankings_count_one_side_of_the_branded_split(
        self,
        _name: str,
        target_domains: list[str],
        branded: str,
        expected_counts: tuple[int, ...],
        expected_domains: list[str],
        expected_searches: list[str],
        expected_rankings: tuple[int, list[str]],
    ) -> None:
        ids = self._import_prompts(
            [
                {"prompt": "is example good for funnels?"},
                {"prompt": "how does example.com price replay?"},
                {"prompt": "Is EXAMPLE's replay fast?"},
                {"prompt": "are examples of funnels useful?"},
                {"prompt": "best funnel tools?"},
            ]
        )
        ours, rival = "https://example.com/pricing", "https://rival.example.org/x"
        self._record_check(ids["is example good for funnels?"], "exa-answer", minutes_ago=10, answer_text="Example.")
        self._record_check(
            ids["how does example.com price replay?"],
            "exa-answer",
            minutes_ago=10,
            cited=True,
            position=1,
            cited_urls=[ours],
            search_queries=["example pricing"],
        )
        self._record_check(ids["Is EXAMPLE's replay fast?"], "exa-answer", minutes_ago=10, answer_text="Yes.")
        self._record_check(
            ids["are examples of funnels useful?"], "exa-answer", minutes_ago=10, answer_text="Example has funnels."
        )
        self._record_check(
            ids["best funnel tools?"],
            "exa-answer",
            minutes_ago=10,
            answer_text="Rival.",
            cited_urls=[rival],
            search_queries=["funnel tools"],
        )
        self._record_check(ids["best funnel tools?"], "claude-web-search", minutes_ago=10, check_failed=True)
        self._record_check(
            ids["is example good for funnels?"], "exa-answer", minutes_ago=35 * 24 * 60, answer_text="Example."
        )
        self._record_check(ids["best funnel tools?"], "exa-answer", minutes_ago=35 * 24 * 60, answer_text="None.")

        for domain in target_domains:
            create_own_brand(self.team, domain)
        overview = self.client.get(f"{self.url}overview/", {"branded": branded}).json()
        rankings = self.client.get(f"{self.url}rankings/", {"branded": branded}).json()

        current, previous = overview["current"], overview["previous"]
        assert overview["branded"] == rankings["branded"] == branded
        assert (
            current["checks"],
            current["failed"],
            current["mentioned"],
            current["cited"],
            previous["checks"],
            previous["mentioned"],
            overview["prompts_tracked"],
            overview["branded_answers"],
            overview["non_branded_answers"],
        ) == expected_counts
        assert [row["domain"] for row in overview["top_domains"]] == expected_domains
        assert [row["query"] for row in overview["top_searches"]] == expected_searches
        assert (rankings["answers"], sorted(row["url"] for row in rankings["top_pages"])) == expected_rankings

    def test_overview_rejects_an_unknown_branded_value(self) -> None:
        assert self.client.get(f"{self.url}overview/?branded=yes").status_code == status.HTTP_400_BAD_REQUEST

    def test_overview_rejects_a_window_outside_the_bounds(self) -> None:
        assert self.client.get(f"{self.url}overview/?days=0").status_code == status.HTTP_400_BAD_REQUEST

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

    def _brand(self, team: Team, domain: str, kind: str = "unknown") -> str:
        brand = AEOBrand.objects.for_team(team.id).create(
            team=team, name=domain.split(".")[0], domain=domain, kind=kind, source="citations"
        )
        return str(brand.id)

    def test_brands_list_by_domain_and_update_relabels(self) -> None:
        url = f"/api/projects/{self.team.id}/aeo_brands/"
        self._brand(self.team, "statsig.com")
        amplitude_id = self._brand(self.team, "amplitude.com")
        self._brand(self.team, "reddit.com", kind="publisher")

        first_page = self.client.get(f"{url}?limit=2").json()
        second_page = self.client.get(f"{url}?limit=2&offset=2").json()
        response = self.client.patch(
            f"{url}{amplitude_id}/",
            {
                "kind": "competitor",
                "status": "confirmed",
                "aliases": [" Amplitude Analytics ", "Amplitude Analytics"],
            },
            format="json",
        )

        assert first_page["count"] == 3
        assert [brand["domain"] for brand in first_page["results"] + second_page["results"]] == [
            "amplitude.com",
            "reddit.com",
            "statsig.com",
        ]
        assert response.status_code == status.HTTP_200_OK, response.json()
        assert {key: response.json()[key] for key in ("kind", "status", "aliases")} == {
            "kind": "competitor",
            "status": "confirmed",
            "aliases": ["Amplitude Analytics"],
        }
        competitors = self.client.get(f"{url}?kind=competitor").json()["results"]
        assert [brand["domain"] for brand in competitors] == ["amplitude.com"]
        searched = self.client.get(f"{url}?search=STAT").json()["results"]
        assert [brand["domain"] for brand in searched] == ["statsig.com"]

    @parameterized.expand(
        [
            (
                "url_becomes_registrable_domain",
                {"domain": "https://Docs.Example.com/pricing", "kind": "own", "aliases": [" Example ", "Example"]},
                status.HTTP_201_CREATED,
                {"domain": "example.com", "name": "Example", "kind": "own", "aliases": ["Example"]},
            ),
            (
                "bare_host_with_a_name",
                {"domain": "rival.example.org", "kind": "competitor", "name": "Rival"},
                status.HTTP_201_CREATED,
                {"domain": "example.org", "name": "Rival", "kind": "competitor", "aliases": []},
            ),
            ("invalid_domain", {"domain": "not a domain", "kind": "own"}, status.HTTP_400_BAD_REQUEST, None),
            ("space_in_a_label", {"domain": "not a domain.com", "kind": "own"}, status.HTTP_400_BAD_REQUEST, None),
            ("underscore_in_a_label", {"domain": "my_site.com", "kind": "own"}, status.HTTP_400_BAD_REQUEST, None),
            ("label_ends_with_a_hyphen", {"domain": "example-.com", "kind": "own"}, status.HTTP_400_BAD_REQUEST, None),
            ("missing_kind", {"domain": "example.com"}, status.HTTP_400_BAD_REQUEST, None),
        ]
    )
    def test_brands_create(self, _name: str, body: dict, expected_status: int, expected: dict | None) -> None:
        self._brand(self.team, "example.net")
        other_team = Team.objects.create(organization=self.organization, name="Other")
        self._brand(other_team, "example.com")
        self._brand(other_team, "example.org")

        response = self.client.post(f"/api/projects/{self.team.id}/aeo_brands/", body, format="json")

        assert response.status_code == expected_status, response.json()
        if expected is None:
            assert AEOBrand.objects.for_team(self.team.id).count() == 1
            return
        brand = response.json()
        assert {key: brand[key] for key in expected} == expected
        assert (brand["status"], brand["source"]) == ("confirmed", "manual")
        assert AEOBrand.objects.for_team(other_team.id).count() == 2

    @parameterized.expand(
        [
            ("create_own", None, {"domain": "example.com", "kind": "own"}, 1),
            ("create_competitor", None, {"domain": "example.com", "kind": "competitor"}, 0),
            ("relabel_to_own", "competitor", {"kind": "own"}, 1),
            ("relabel_own_to_competitor", "own", {"kind": "competitor"}, 1),
            ("ignore_own", "own", {"status": "ignored"}, 1),
            # Any kind or status edit, since concurrent edits can each look like no change.
            ("confirm_own", "own", {"status": "confirmed"}, 1),
            ("relabel_competitor_as_competitor", "competitor", {"kind": "competitor"}, 1),
            ("rename_own", "own", {"name": "Example Inc", "aliases": ["Example"]}, 0),
        ]
    )
    def test_own_brand_changes_recompute_past_citations_after_commit(
        self, _name: str, existing_kind: str | None, body: dict, expected_calls: int
    ) -> None:
        url = f"/api/projects/{self.team.id}/aeo_brands/"
        brand_id = self._brand(self.team, "example.com", kind=existing_kind) if existing_kind else None

        with (
            patch("products.aeo.backend.facade.api.recompute_aeo_own_citations_task") as task,
            self.captureOnCommitCallbacks(execute=True),
        ):
            if brand_id is None:
                response = self.client.post(url, body, format="json")
            else:
                response = self.client.patch(f"{url}{brand_id}/", body, format="json")

        assert response.status_code in (status.HTTP_200_OK, status.HTTP_201_CREATED), response.json()
        assert task.apply_async.call_count == expected_calls
        if expected_calls:
            task.apply_async.assert_called_with((self.team.id,), countdown=RECOMPUTE_DEBOUNCE_SECONDS)

    def test_a_burst_of_own_brand_edits_queues_one_recompute(self) -> None:
        brand_id = self._brand(self.team, "example.com", kind="competitor")
        url = f"/api/projects/{self.team.id}/aeo_brands/{brand_id}/"

        with (
            patch("products.aeo.backend.facade.api.recompute_aeo_own_citations_task") as task,
            self.captureOnCommitCallbacks(execute=True),
        ):
            for kind in ("own", "competitor", "own"):
                assert self.client.patch(url, {"kind": kind}, format="json").status_code == status.HTTP_200_OK

        assert task.apply_async.call_count == 1

    def test_a_failed_recompute_enqueue_keeps_the_brand_change(self) -> None:
        with (
            patch("products.aeo.backend.facade.api.recompute_aeo_own_citations_task") as task,
            self.captureOnCommitCallbacks(execute=True),
        ):
            task.apply_async.side_effect = ConnectionError("broker unavailable")
            response = self.client.post(
                f"/api/projects/{self.team.id}/aeo_brands/", {"domain": "example.com", "kind": "own"}, format="json"
            )

        assert response.status_code == status.HTTP_201_CREATED
        assert AEOBrand.objects.for_team(self.team.id).filter(domain="example.com", kind="own").exists()

    def test_brands_create_rejects_a_known_domain_with_a_pointer_to_update(self) -> None:
        self._brand(self.team, "example.com")

        response = self.client.post(
            f"/api/projects/{self.team.id}/aeo_brands/", {"domain": "example.com", "kind": "own"}, format="json"
        )

        assert response.status_code == status.HTTP_400_BAD_REQUEST
        assert "Update the existing brand" in json.dumps(response.json())

    @parameterized.expand([("get", None), ("patch", {"status": "ignored"})])
    def test_another_teams_brand_is_not_found(self, method: str, body: dict | None) -> None:
        other_team = Team.objects.create(organization=self.organization, name="Other")
        brand_id = self._brand(other_team, "amplitude.com")

        response = getattr(self.client, method)(
            f"/api/projects/{self.team.id}/aeo_brands/{brand_id}/", body, format="json"
        )

        assert response.status_code == status.HTTP_404_NOT_FOUND
        assert AEOBrand.objects.for_team(other_team.id).get(id=brand_id).status == "suggested"

    @parameterized.expand(
        [
            ("answer", True, "completed", ["Best session replay tool?"], 1),
            ("paused", True, "completed", ["Best session replay tool?"], 2),
            ("cut_off", True, "completed", ["Best session replay tool?"], 1),
            ("timeout", True, "failed", [], 1),
            ("answer", False, None, [], 0),
        ]
    )
    def test_suggest_runs_as_a_job_and_never_saves_prompts(
        self, outcome: str, ai_approved: bool, final_status: str | None, expected_prompts: list[str], calls: int
    ) -> None:
        self.organization.is_ai_data_processing_approved = ai_approved
        self.organization.save(update_fields=["is_ai_data_processing_approved"])
        self.client.post(
            f"{self.url}bulk_import/",
            {"prompts": [{"prompt": "Tracked already?"}, {"prompt": "Old wording?"}]},
            format="json",
        )
        old_id = next(r["id"] for r in self.client.get(self.url).json()["results"] if r["prompt"] == "Old wording?")
        self.client.patch(f"{self.url}{old_id}/", {"prompt": "New wording?"}, format="json")
        items = [
            {"prompt": p, "topic": "Replay", "circle": "battleground", "funnel_stage": "bottom", "branded": False}
            for p in ["Best session replay tool?", "Tracked already?", "Old wording?"]
        ]
        paused = MagicMock(status_code=200)
        paused.json.return_value = {"stop_reason": "pause_turn", "content": [{"type": "text", "text": "Reading."}]}
        answered = MagicMock(status_code=200)
        answered.json.return_value = {
            "stop_reason": "end_turn",
            "content": [{"type": "text", "text": json.dumps(items)}],
        }
        # The token limit cut the array mid-way through its second object.
        cut_off = MagicMock(status_code=200)
        cut_off.json.return_value = {
            "stop_reason": "max_tokens",
            "content": [{"type": "text", "text": json.dumps(items[:1])[:-1] + ', {"prompt": "Half'}],
        }
        post = MagicMock(
            side_effect={
                "answer": [answered],
                "paused": [paused, answered],
                "cut_off": [cut_off],
                "timeout": requests.Timeout(),
            }[outcome]
        )
        gateway = MagicMock(url="http://gateway", api_key="test-key")

        with (
            patch("products.aeo.backend.suggestions.resolve_ai_gateway_config", return_value=gateway),
            patch("products.aeo.backend.suggestions.requests.Session.post", post),
        ):
            started = self.client.post(f"{self.url}suggest/", {"domain": "example.com"}, format="json")

        assert post.call_count == calls
        assert AEOPrompt.objects.for_team(self.team.id).count() == 2
        if final_status is None:
            assert started.status_code == status.HTTP_403_FORBIDDEN
            return
        assert started.status_code == status.HTTP_202_ACCEPTED, started.json()
        assert started.json()["status"] == "pending"
        job = self.client.get(f"{self.url}suggest/{started.json()['id']}/").json()
        assert job["status"] == final_status
        assert [s["prompt"] for s in job["suggestions"]] == expected_prompts
        if outcome == "paused":
            resumed = post.call_args_list[1].kwargs["json"]["messages"]
            assert resumed[-1] == {"role": "assistant", "content": [{"type": "text", "text": "Reading."}]}

    def test_a_pending_job_past_its_deadline_reads_as_failed(self) -> None:
        with patch("products.aeo.backend.facade.api.suggest_aeo_prompts_task.delay"):
            started = self.client.post(f"{self.url}suggest/", {"domain": "example.com"}, format="json").json()

        with time_machine.travel(timezone.now() + dt.timedelta(minutes=9), tick=False):
            job = self.client.get(f"{self.url}suggest/{started['id']}/").json()

        assert job["status"] == "failed"
        assert job["error"] == "Prompt suggestions stopped before they finished. Try again."

    def test_import_records_that_a_prompt_came_from_a_suggestion(self) -> None:
        self.client.post(
            f"{self.url}bulk_import/",
            {"prompts": [{"prompt": "Suggested?", "origin": "suggestion"}, {"prompt": "Written?"}]},
            format="json",
        )

        evidence = {p.prompt: p.evidence for p in AEOPrompt.objects.for_team(self.team.id)}
        assert evidence["Suggested?"]["via"] == "suggestion"
        assert evidence["Written?"]["via"] == "api"

    def test_suggestion_get_returns_404_for_an_unknown_job(self) -> None:
        response = self.client.get(f"{self.url}suggest/{uuid.uuid4()}/")
        assert response.status_code == status.HTTP_404_NOT_FOUND

    def _enabled(self, *, allowlisted: bool = True):
        return (
            self.settings(AEO_CITATION_TEAM_IDS=[str(self.team.id)] if allowlisted else []),
            patch("products.aeo.backend.tasks.tasks.feature_enabled_or_false", return_value=True),
        )

    @parameterized.expand(
        [
            ("queued", True, False, status.HTTP_202_ACCEPTED, "queued", 1),
            ("already_running", True, True, status.HTTP_202_ACCEPTED, "already_running", 0),
            ("not_enabled", False, False, status.HTTP_403_FORBIDDEN, None, 0),
        ]
    )
    def test_run_starts_a_citation_run_only_when_none_is_running_for_an_enabled_project(
        self,
        _name: str,
        allowlisted: bool,
        run_in_progress: bool,
        expected_status: int,
        expected_run_status: str | None,
        expected_queued: int,
    ) -> None:
        self.addCleanup(get_client().delete, f"aeo_citation_run_queued:{self.team.id}")
        if run_in_progress:
            assert get_client().lock(f"aeo_citation_run:{self.team.id}", timeout=60).acquire(blocking=False)
            self.addCleanup(get_client().delete, f"aeo_citation_run:{self.team.id}")

        settings_override, flag = self._enabled(allowlisted=allowlisted)
        with (
            settings_override,
            flag,
            patch("products.aeo.backend.facade.api.run_aeo_citation_checks_for_team_task") as task,
        ):
            response = self.client.post(f"{self.url}run/")

        assert response.status_code == expected_status, response.json()
        if expected_run_status:
            assert response.json() == {"status": expected_run_status}
        assert task.delay.call_count == expected_queued

    def test_run_allowance_is_spent_only_on_runs_that_get_queued(self) -> None:
        queued_key = f"aeo_citation_run_queued:{self.team.id}"
        self.addCleanup(get_client().delete, queued_key)
        for key in get_client().keys(f"aeo_manual_runs:{self.team.id}:*"):
            get_client().delete(key)
        self.addCleanup(
            lambda: [get_client().delete(key) for key in get_client().keys(f"aeo_manual_runs:{self.team.id}:*")]
        )

        settings_override, flag = self._enabled()
        statuses = []
        with (
            settings_override,
            flag,
            self.settings(AEO_MANUAL_RUNS_PER_DAY=2),
            patch("products.aeo.backend.facade.api.run_aeo_citation_checks_for_team_task") as task,
        ):
            for step in ("first", "while_queued", "broker_down", "second", "over_cap"):
                if step != "while_queued":
                    get_client().delete(queued_key)
                task.delay.side_effect = RuntimeError("broker down") if step == "broker_down" else None
                response = self.client.post(f"{self.url}run/")
                body = response.json() if response.status_code < 500 else {}
                statuses.append((step, response.status_code, body.get("status")))

        assert statuses == [
            ("first", status.HTTP_202_ACCEPTED, "queued"),
            ("while_queued", status.HTTP_202_ACCEPTED, "already_running"),
            ("broker_down", status.HTTP_500_INTERNAL_SERVER_ERROR, None),
            ("second", status.HTTP_202_ACCEPTED, "queued"),
            ("over_cap", status.HTTP_429_TOO_MANY_REQUESTS, None),
        ]
        assert not get_client().exists(queued_key), "a refused run must not leave the queued marker behind"

    def test_score_sentiment_reuses_the_running_job_on_the_aeo_queue(self) -> None:
        settings_override, flag = self._enabled()
        with (
            settings_override,
            flag,
            patch("products.aeo.backend.temporal.brand_sentiment.sync_connect") as connect,
            patch("products.aeo.backend.temporal.brand_sentiment.asyncio.run"),
        ):
            first = self.client.post(f"{self.url}score_sentiment/")
            second = self.client.post(f"{self.url}score_sentiment/")

        assert (first.status_code, second.status_code) == (status.HTTP_202_ACCEPTED, status.HTTP_202_ACCEPTED)
        assert first.json() == second.json() == {"workflow_id": f"aeo-brand-sentiment-{self.team.id}-backlog"}
        start = connect.return_value.start_workflow.call_args
        assert start.args[1].run_id is None, "a backlog pass must not filter on a run id"
        kwargs = start.kwargs
        assert (kwargs["task_queue"], kwargs["id_conflict_policy"]) == (
            settings.AEO_TASK_QUEUE,
            WorkflowIDConflictPolicy.USE_EXISTING,
        )

    @parameterized.expand([("not_enabled", False, None, 403), ("temporal_down", True, RuntimeError("down"), 503)])
    def test_score_sentiment_refuses_cleanly(
        self, _name: str, allowlisted: bool, connect_error: Exception | None, expected_status: int
    ) -> None:
        settings_override, flag = self._enabled(allowlisted=allowlisted)
        with (
            settings_override,
            flag,
            patch("products.aeo.backend.temporal.brand_sentiment.sync_connect", side_effect=connect_error),
            patch("products.aeo.backend.temporal.brand_sentiment.asyncio.run"),
        ):
            response = self.client.post(f"{self.url}score_sentiment/")

        assert response.status_code == expected_status, response.json()


class TestAEOKeywordAPI(APIBaseTest):
    def setUp(self) -> None:
        super().setUp()
        flag_patcher = patch(
            "products.aeo.backend.presentation.views.posthog_feature_flag_enabled",
            return_value=True,
        )
        self.feature_enabled = flag_patcher.start()
        self.addCleanup(flag_patcher.stop)
        self.url = f"/api/projects/{self.team.id}/aeo_keywords/"
        self._prompts: dict[str, AEOPrompt] = {}

    def _record(
        self,
        prompt_text: str,
        *,
        engine: str = "openai-web-search",
        searches: list[str] | None = None,
        answer_text: str | None = None,
        cited: bool = False,
        position: int | None = None,
        check_failed: bool = False,
        days_ago: int = 0,
    ) -> None:
        with team_scope(self.team.pk):
            prompt = self._prompts.get(prompt_text)
            if prompt is None:
                prompt = AEOPrompt.objects.create(
                    team=self.team,
                    prompt=prompt_text,
                    prompt_hash=str(uuid.uuid4()),
                    prompt_source=AEOPrompt.Source.MANUAL,
                )
                self._prompts[prompt_text] = prompt
            check = AEOCitationCheck.objects.create(
                team=self.team,
                prompt=prompt,
                run_id=uuid.uuid4(),
                prompt_text=prompt_text,
                prompt_source=prompt.prompt_source,
                prompt_hash=prompt.prompt_hash,
                engine=engine,
                model=engine,
                cited=cited,
                target_best_position=position,
                check_failed=check_failed,
                answer_text=answer_text,
                search_queries=searches or [],
            )
            AEOCitationCheck.objects.filter(id=check.id).update(
                created_at=timezone.now() - dt.timedelta(days=days_ago, minutes=5)
            )

    def _keywords(self) -> list[str]:
        return [row["keyword"] for row in self.client.get(self.url).json()]

    def test_requires_the_rollout_flag(self) -> None:
        self.feature_enabled.return_value = False

        assert self.client.get(self.url).status_code == status.HTTP_403_FORBIDDEN
        response = self.client.post(self.url, {"keywords": ["pricing"]}, format="json")
        assert response.status_code == status.HTTP_403_FORBIDDEN
        assert self.client.get(f"{self.url}report/").status_code == status.HTTP_403_FORBIDDEN
        assert not AEOKeyword.objects.for_team(self.team.id).exists()

    def test_create_skips_blanks_and_duplicates_then_delete_removes_one(self) -> None:
        self.client.post(self.url, {"keywords": ["pricing"]}, format="json")

        response = self.client.post(
            self.url,
            {"keywords": ["  Session   Replay ", "session replay", "", "   ", "PRICING", "x" * 150, "feature flags"]},
            format="json",
        )

        assert response.status_code == status.HTTP_201_CREATED, response.json()
        assert response.json() == {"created": 2, "skipped": 5}
        assert self._keywords() == ["feature flags", "pricing", "session replay"]

        keyword_id = self.client.get(self.url).json()[0]["id"]
        assert self.client.get(f"{self.url}{keyword_id}/").json()["keyword"] == "feature flags"
        assert self.client.delete(f"{self.url}{keyword_id}/").status_code == status.HTTP_204_NO_CONTENT
        assert self._keywords() == ["pricing", "session replay"]

        child = Team.objects.create(organization=self.organization, name="child env", parent_team=self.team)
        assert create_keywords(child.id, ["roadmap", "pricing"]).created == 1
        assert self._keywords() == ["pricing", "roadmap", "session replay"]

    @parameterized.expand(
        [
            ("at_the_cap", 195, 5, status.HTTP_201_CREATED, 200),
            ("past_the_cap", 195, 6, status.HTTP_400_BAD_REQUEST, 195),
        ]
    )
    def test_create_enforces_the_keyword_cap(
        self, _name: str, existing: int, adding: int, expected_status: int, expected_count: int
    ) -> None:
        self.client.post(self.url, {"keywords": [f"existing {i}" for i in range(existing)]}, format="json")

        response = self.client.post(self.url, {"keywords": [f"new {i}" for i in range(adding)]}, format="json")

        assert response.status_code == expected_status, response.json()
        if expected_status == status.HTTP_400_BAD_REQUEST:
            assert "up to 200 keywords" in response.json()["detail"]
        assert AEOKeyword.objects.for_team(self.team.id).count() == expected_count

    @parameterized.expand([("retrieve", "get"), ("delete", "delete")])
    def test_another_teams_keyword_is_not_found(self, _name: str, method: str) -> None:
        other_team = Team.objects.create(organization=self.organization, name="Other")
        with team_scope(other_team.pk):
            other_keyword = AEOKeyword.objects.create(team=other_team, keyword="pricing")

        response = getattr(self.client, method)(f"{self.url}{other_keyword.id}/")

        assert response.status_code == status.HTTP_404_NOT_FOUND
        assert self._keywords() == []
        with team_scope(other_team.pk):
            assert AEOKeyword.objects.filter(id=other_keyword.id).exists()

    @time_machine.travel("2026-10-20T12:00:00Z", tick=False)
    def test_report_measures_each_keyword_in_prompts_searches_and_answers(self) -> None:
        self.client.post(self.url, {"keywords": ["session replay", "pricing", "zebra"]}, format="json")
        replay, cost = "Best session replay tool?", "How much does product analytics cost?"
        self._record(
            replay,
            engine="claude-web-search",
            searches=["session replay tools 2026", "example pricing"],
            answer_text="Example offers session replay. Session replay is free.",
            cited=True,
            position=2,
        )
        self._record(replay, searches=["best session replay"], answer_text="Acme has session replay. Example too.")
        self._record(cost, searches=["product analytics pricing"], answer_text="Pricing varies. Acme pricing is free.")
        self._record(
            cost, engine="exa-answer", answer_text="Session replay pricing at Example.", cited=True, position=1
        )
        self._record(replay, check_failed=True)
        self._record(replay, searches=["session replay"], answer_text="Session replay", cited=True, days_ago=10)

        create_own_brand(self.team, "example.com")
        response = self.client.get(f"{self.url}report/?days=7")

        assert response.status_code == status.HTTP_200_OK, response.json()
        body = response.json()
        assert (body["answers"], body["brand_names"], body["window_from"]) == (4, ["example"], "2026-10-14")
        rows = {row.pop("keyword"): row for row in body["keywords"]}
        assert rows["session replay"] == {
            "prompts": 1,
            "prompt_checks": 2,
            "prompt_mention_rate": 1.0,
            "prompt_cited_rate": 0.5,
            "searched_checks": 2,
            "searched_rate": 0.5,
            "searched_cited_rate": 0.5,
            "answer_checks": 3,
            "answer_rate": 0.75,
            "uses_per_answer": pytest.approx(4 / 3),
            "answer_mention_rate": 1.0,
            "avg_citation_position": 1.5,
            "median_first_mention_depth": pytest.approx(25 / 37),
        }
        assert rows["pricing"] == {
            "prompts": 0,
            "prompt_checks": 0,
            "prompt_mention_rate": None,
            "prompt_cited_rate": None,
            "searched_checks": 2,
            "searched_rate": 0.5,
            "searched_cited_rate": 0.5,
            "answer_checks": 2,
            "answer_rate": 0.5,
            "uses_per_answer": 1.5,
            "answer_mention_rate": 0.5,
            "avg_citation_position": 1.0,
            "median_first_mention_depth": pytest.approx(26 / 34),
        }
        assert rows["zebra"]["answer_rate"] == 0.0
        assert rows["zebra"]["uses_per_answer"] is None

        self.client.post(self.url, {"keywords": ["acme"]}, format="json")
        refreshed = self.client.get(f"{self.url}report/?days=7").json()
        assert [row["keyword"] for row in refreshed["keywords"]] == ["acme", "pricing", "session replay", "zebra"]
        assert next(row for row in refreshed["keywords"] if row["keyword"] == "acme")["answer_checks"] == 2

    @parameterized.expand(
        [
            (
                "all_answers",
                "",
                4,
                [
                    ("acme", "competitor", 2, 0.0),
                    ("self hosted", "other", 2, 0.5),
                    ("2026", "freshness", 1, 1.0),
                    ("acme.io", "competitor", 1, 0.0),
                    ("example", "other", 1, 0.0),
                    ("pricing", "pricing", 1, 1.0),
                    ("site:example.com", "site", 1, 0.0),
                    ("vs acme", "comparison", 1, 0.0),
                ],
            ),
            (
                "keyword_filter",
                "&keyword=Self%20Hosted",
                2,
                [
                    ("self hosted", "other", 2, 0.5),
                    ("2026", "freshness", 1, 1.0),
                    ("acme", "competitor", 1, 0.0),
                    ("pricing", "pricing", 1, 1.0),
                ],
            ),
        ]
    )
    @time_machine.travel("2026-10-20T12:00:00Z", tick=False)
    def test_modifiers_count_new_search_words_once_per_answer(
        self, _name: str, query: str, expected_answers: int, expected: list[tuple[str, str, int, float]]
    ) -> None:
        with team_scope(self.team.pk):
            AEOBrand.objects.create(
                team=self.team, name="Acme Analytics", domain="acme.io", kind="competitor", source="manual"
            )
        self._record(
            "best analytics tool",
            engine="claude-web-search",
            searches=["self hosted analytics 2026", "self hosted analytics pricing"],
            cited=True,
        )
        self._record("analytics for startups", searches=["self hosted analytics", "acme"])
        self._record("web analytics", searches=["site:example.com analytics", "example com vs acme", "acme.io"])
        self._record("privacy analytics", engine="exa-answer", cited=True)
        self._record("web analytics", searches=["acme pricing"], check_failed=True)

        response = self.client.get(f"{self.url}modifiers/?days=7{query}")

        assert response.status_code == status.HTTP_200_OK, response.json()
        body = response.json()
        assert (body["answers"], body["baseline_cited_rate"]) == (expected_answers, 0.5)
        assert [(row["term"], row["kind"], row["answers"], row["cited_rate"]) for row in body["modifiers"]] == expected
        self_hosted = next(row for row in body["modifiers"] if row["term"] == "self hosted")
        assert self_hosted["share"] == 2 / expected_answers
        assert self_hosted["engines"] == [
            {"engine": "claude-web-search", "answers": 1},
            {"engine": "openai-web-search", "answers": 1},
        ]
        assert self_hosted["example_searches"] == ["self hosted analytics 2026", "self hosted analytics"]

    @parameterized.expand([("report",), ("modifiers",)])
    @patch("posthog.rate_limit.is_rate_limit_enabled", return_value=True)
    def test_report_endpoints_are_throttled_for_the_session_authenticated_ui(
        self, endpoint: str, _rate_limit_enabled: MagicMock
    ) -> None:
        cache.clear()
        self.addCleanup(cache.clear)

        with patch.object(AEOKeywordReportBurstRateThrottle, "rate", "2/minute"):
            statuses = [self.client.get(f"{self.url}{endpoint}/").status_code for _ in range(3)]

        assert statuses == [status.HTTP_200_OK, status.HTTP_200_OK, status.HTTP_429_TOO_MANY_REQUESTS]

    @parameterized.expand(
        [
            ("answer", True, 1, status.HTTP_202_ACCEPTED, "completed", ["session replay"]),
            ("timeout", True, 1, status.HTTP_202_ACCEPTED, "failed", []),
            ("answer", False, 1, status.HTTP_403_FORBIDDEN, None, []),
            ("answer", True, 200, status.HTTP_400_BAD_REQUEST, None, []),
        ]
    )
    def test_suggest_runs_as_a_job_and_never_saves_keywords(
        self,
        outcome: str,
        ai_approved: bool,
        tracked: int,
        start_status: int,
        final_status: str | None,
        expected: list[str],
    ) -> None:
        self.organization.is_ai_data_processing_approved = ai_approved
        self.organization.save(update_fields=["is_ai_data_processing_approved"])
        create_keywords(self.team.id, ["pricing", *(f"keyword {i}" for i in range(tracked - 1))])
        self._record("Best session replay tool?", searches=["session replay tools", "Session  replay pricing"])
        answered = MagicMock(status_code=200)
        answered.json.return_value = {
            "stop_reason": "end_turn",
            "content": [
                {
                    "type": "text",
                    "text": json.dumps(
                        [
                            {"keyword": "session replay", "reason": "Buyers search for it."},
                            {"keyword": "Pricing", "reason": "Already tracked."},
                        ]
                    ),
                }
            ],
        }
        post = MagicMock(side_effect={"answer": [answered], "timeout": requests.Timeout()}[outcome])
        gateway = MagicMock(url="http://gateway", api_key="test-key")

        with (
            patch("products.aeo.backend.keyword_suggestions.resolve_ai_gateway_config", return_value=gateway),
            patch("products.aeo.backend.llm.requests.Session.post", post),
        ):
            started = self.client.post(f"{self.url}suggest/", {"domain": "example.com"}, format="json")

        assert started.status_code == start_status, started.json()
        assert AEOKeyword.objects.for_team(self.team.id).count() == tracked
        if final_status is None:
            assert post.call_count == 0
            return
        instructions = post.call_args.kwargs["json"]["messages"][0]["content"]
        assert "- session replay pricing (1)" in instructions
        assert "- Best session replay tool?" in instructions
        job = self.client.get(f"{self.url}suggest/{started.json()['id']}/").json()
        assert job["status"] == final_status
        # Two of the check's searches contain the keyword, and the check counts once, as in the keyword report.
        assert [(s["keyword"], s["searched_checks"]) for s in job["suggestions"]] == [(k, 1) for k in expected]

    def test_suggestion_get_returns_404_for_an_unknown_job(self) -> None:
        response = self.client.get(f"{self.url}suggest/{uuid.uuid4()}/")
        assert response.status_code == status.HTTP_404_NOT_FOUND
