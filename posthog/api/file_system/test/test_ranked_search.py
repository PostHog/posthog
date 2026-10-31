from datetime import date, timedelta

from posthog.test.base import APIBaseTest

from django.test import SimpleTestCase
from django.utils import timezone

from parameterized import parameterized
from rest_framework import status

from posthog.api.file_system.ranked_search import MAX_TOKENS, FileSystemRankedSearch
from posthog.models import Team
from posthog.models.file_system.file_system import FileSystem, split_path
from posthog.models.file_system.file_system_view_log import FileSystemViewLog


class TestFileSystemRankedSearch(APIBaseTest):
    def _create(self, path: str, type: str = "insight", days_ago: int = 0, ref: str | None = None) -> FileSystem:
        return FileSystem.objects.create(
            team=self.team,
            path=path,
            type=type,
            ref=ref,
            created_by=self.user,
            created_at=timezone.now() - timedelta(days=days_ago),
        )

    def _search(self, search: str, **params: int) -> dict:
        data: dict[str, str | int] = {"search": search, **params}
        response = self.client.get(f"/api/projects/{self.team.id}/file_system/search/", data)
        self.assertEqual(response.status_code, status.HTTP_200_OK, response.json())
        return response.json()

    def _names(self, data: dict) -> list[str]:
        return [split_path(item["entry"]["path"])[-1] for item in data["results"]]

    @parameterized.expand(
        [
            (
                "exact_name_before_prefix_and_substring",
                "revenue",
                ["Unfiled/Insights/Monthly revenue", "Unfiled/Insights/Revenue forecast", "Unfiled/Insights/Revenue"],
                ["Revenue", "Revenue forecast", "Monthly revenue"],
            ),
            (
                "every_word_must_match_when_possible",
                "signup funnel",
                ["Unfiled/Insights/Signup funnel", "Unfiled/Insights/Signup count", "Unfiled/Insights/Checkout funnel"],
                ["Signup funnel"],
            ),
            (
                "plural_name_counts_as_exact",
                "survey",
                ["Unfiled/Feature Flags/survey-targeting-abc", "Unfiled/Dashboards/Surveys"],
                ["Surveys", "survey-targeting-abc"],
            ),
            (
                "typo_still_finds_the_word",
                "retension",
                ["Unfiled/Insights/Weekly retention", "Unfiled/Insights/Pageviews"],
                ["Weekly retention"],
            ),
            (
                "typo_in_a_name_with_an_escaped_slash",
                "retension",
                ["Unfiled/Insights/Retention \\/ Weekly", "Unfiled/Insights/Pageviews"],
                ["Retention / Weekly"],
            ),
            (
                "name_match_before_folder_match",
                "growth",
                ["Growth team/Signups", "Unfiled/Insights/Growth weekly"],
                ["Growth weekly", "Signups"],
            ),
            (
                "plural_query_matches_singular_name",
                "surveys",
                ["Unfiled/Insights/Survey results", "Unfiled/Insights/Surveys archive"],
                ["Surveys archive", "Survey results"],
            ),
            (
                "repeated_word_gets_no_proximity_bonus",
                "sign signup",
                ["Unfiled/Insights/Signup", "Unfiled/Insights/Sign signup"],
                ["Sign signup", "Signup"],
            ),
            (
                "exact_folder_word_beats_name_typo",
                "growth",
                ["Growth/Growht", "Unfiled/Insights/Growth report"],
                ["Growth report", "Growht"],
            ),
        ]
    )
    def test_ranks_matches(self, _name: str, search: str, paths: list[str], expected: list[str]) -> None:
        for days_ago, path in enumerate(paths):
            self._create(path, type="dashboard" if "/Dashboards/" in path else "insight", days_ago=days_ago)

        self.assertEqual(self._names(self._search(search)), expected)

    @parameterized.expand(
        [
            ("unknown_word", "xyzzy report", ["Weekly report"], ["Weekly report"], ["report"]),
            ("word_with_a_colon", "revenue: xyzzy", ["Revenue - Q1"], ["Revenue - Q1"], ["revenue"]),
            (
                "close_spelling_the_ranker_rejects",
                "addon journey",
                ["Journey: platform add-on trial", "Journey funnel"],
                ["Journey: platform add-on trial", "Journey funnel"],
                ["journey"],
            ),
            (
                "more_words_beat_fewer_typos",
                "signup retension xyzzy",
                ["Signup retention", "Signup"],
                ["Signup retention"],
                ["signup", "retension"],
            ),
            (
                "rejected_candidate_does_not_stop_the_typo_fallback",
                "xyzzy retension",
                ["prexyzzyabc", "Weekly retention"],
                ["Weekly retention"],
                ["retension"],
            ),
        ]
    )
    def test_falls_back_to_some_words_and_says_which(
        self, _name: str, search: str, names: list[str], expected: list[str], matched_words: list[str]
    ) -> None:
        for days_ago, name in enumerate(names):
            self._create(f"Unfiled/Insights/{name}", days_ago=days_ago)

        data = self._search(search)

        self.assertEqual(self._names(data), expected)
        self.assertFalse(data["matched_all_words"])
        self.assertEqual(data["matched_words"], matched_words)

    def test_frecency_breaks_ties_between_equal_matches(self) -> None:
        self._create("Unfiled/Dashboards/Home", type="dashboard", ref="1", days_ago=1)
        self._create("Unfiled/Dashboards/Home", type="dashboard", ref="2", days_ago=2)
        FileSystemViewLog.objects.create(
            team=self.team, user=self.user, type="dashboard", ref="2", view_days=[timezone.now().date()]
        )

        data = self._search("home")

        self.assertEqual([item["entry"]["ref"] for item in data["results"]], ["2", "1"])

    def test_applies_filters_and_never_returns_other_projects(self) -> None:
        self._create("Unfiled/Insights/Revenue", type="insight")
        self._create("Unfiled/Dashboards/Revenue", type="dashboard")
        other_team = Team.objects.create(organization=self.organization, name="Other project")
        FileSystem.objects.create(team=other_team, path="Unfiled/Dashboards/Revenue elsewhere", type="dashboard")

        data = self._search("type:dashboard revenue")

        self.assertEqual([item["entry"]["type"] for item in data["results"]], ["dashboard"])
        self.assertEqual(data["type_counts"], [{"type": "dashboard", "count": 1}])

    def test_typo_search_covers_every_environment_of_the_project_only(self) -> None:
        self._create("Unfiled/Insights/Retention", type="insight")
        environment = Team.objects.create(organization=self.organization, project=self.project, name="Env-2")
        FileSystem.objects.create(team=environment, path="Unfiled/Dashboards/Retention", type="dashboard")
        other_team = Team.objects.create(organization=self.organization, name="Other project")
        FileSystem.objects.create(team=other_team, path="Unfiled/Notebooks/Retention", type="notebook")

        data = self._search("retension")

        self.assertTrue(data["matched_with_typos"])
        self.assertCountEqual([item["entry"]["type"] for item in data["results"]], ["insight", "dashboard"])

    def test_per_type_previews_include_lower_ranked_types(self) -> None:
        for index in range(5):
            self._create(f"Unfiled/Insights/Revenue {index}", type="insight")
        self._create("Unfiled/Dashboards/Old revenue board", type="dashboard", days_ago=30)

        data = self._search("revenue", limit=2, per_type=1)

        self.assertIn("Old revenue board", self._names(data))
        self.assertEqual(len(data["results"]), 3)

    def test_per_type_previews_skip_names_already_previewed(self) -> None:
        for index in range(4):
            self._create("Unfiled/Insights/Revenue", type="insight", days_ago=index)
        self._create("Unfiled/Insights/Revenue by plan", type="insight", days_ago=10)

        data = self._search("revenue", limit=1, per_type=2)

        self.assertEqual(self._names(data), ["Revenue", "Revenue by plan"])


class TestFileSystemRankedSearchTokens(SimpleTestCase):
    def test_repeated_and_extra_words_are_dropped(self) -> None:
        ranker = FileSystemRankedSearch(
            " ".join(["the"] * 200 + [f"word{index}" for index in range(20)]), user_id=1, team_id=1, today=date.today()
        )

        self.assertEqual(ranker.tokens, ("the", *(f"word{index}" for index in range(MAX_TOKENS - 1))))
