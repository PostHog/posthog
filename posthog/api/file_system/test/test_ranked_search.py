from datetime import timedelta

from posthog.test.base import APIBaseTest

from django.utils import timezone

from parameterized import parameterized
from rest_framework import status

from posthog.models import Team
from posthog.models.file_system.file_system import FileSystem
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
        response = self.client.get(f"/api/projects/{self.team.id}/file_system/search/", {"search": search, **params})
        self.assertEqual(response.status_code, status.HTTP_200_OK, response.json())
        return response.json()

    def _names(self, data: dict) -> list[str]:
        return [item["entry"]["path"].rsplit("/", 1)[-1] for item in data["results"]]

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
                "name_match_before_folder_match",
                "growth",
                ["Growth team/Signups", "Unfiled/Insights/Growth weekly"],
                ["Growth weekly", "Signups"],
            ),
        ]
    )
    def test_ranks_matches(self, _name: str, search: str, paths: list[str], expected: list[str]) -> None:
        for days_ago, path in enumerate(paths):
            self._create(path, type="dashboard" if "/Dashboards/" in path else "insight", days_ago=days_ago)

        self.assertEqual(self._names(self._search(search)), expected)

    def test_falls_back_to_some_words_and_says_which(self) -> None:
        self._create("Unfiled/Insights/Weekly report")

        data = self._search("xyzzy report")

        self.assertEqual(self._names(data), ["Weekly report"])
        self.assertFalse(data["matched_all_words"])
        self.assertEqual(data["matched_words"], ["report"])

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

        self.assertIn("Revenue by plan", self._names(data))
