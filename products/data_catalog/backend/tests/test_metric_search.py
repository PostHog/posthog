from posthog.test.base import APIBaseTest, BaseTest

from django.test import SimpleTestCase

from parameterized import parameterized
from rest_framework import status

from posthog.models.scoping import team_scope

from products.data_catalog.backend.logic.metric_search import search_metrics, split_search
from products.data_catalog.backend.models import Metric
from products.data_catalog.evals.metric_search_cases import LEXICAL_CASE_TYPES, SEARCH_CASES, CaseType, SearchCase
from products.data_catalog.evals.metric_search_runner import LEXICAL, run_case, score_case, seed_metric_search_catalog


def _cases(*case_types: CaseType) -> list[tuple[str, SearchCase]]:
    return [(case.name, case) for case in SEARCH_CASES if case.case_type in case_types]


class TestMetricSearchFixtureCatalog(BaseTest):
    @classmethod
    def setUpTestData(cls) -> None:
        super().setUpTestData()
        seed_metric_search_catalog(cls.team.id)

    @parameterized.expand(_cases(*LEXICAL_CASE_TYPES))
    def test_lexical_lane_finds_the_metric(self, _name: str, case: SearchCase) -> None:
        output = run_case(self.team.id, case, LEXICAL)
        scores = score_case(case, output["ranked"], output["confident_match"])
        assert scores["recall"] == 1.0, output
        if case.case_type == CaseType.NEAR_SIBLING:
            assert scores["sibling_ranked_above"] == 1.0, output

    @parameterized.expand(_cases(CaseType.REAL_GAP))
    def test_real_gap_is_not_a_confident_match(self, _name: str, case: SearchCase) -> None:
        output = run_case(self.team.id, case, LEXICAL)
        assert output["confident_match"] is False, output

    @parameterized.expand(_cases(CaseType.RELATED_WORD))
    def test_related_word_case_shares_no_word_with_its_metric(self, _name: str, case: SearchCase) -> None:
        with team_scope(self.team.id):
            expected = Metric.objects.for_team(self.team.id).filter(name__in=case.expected)
            assert search_metrics(expected, case.queries).hits == [], (
                "A related-word case must not match its metric's stored text, or it only tests word matching again"
            )


class TestSplitSearch(SimpleTestCase):
    @parameterized.expand(
        [
            ("commas_and_spaces", " mrr ,  monthly   recurring revenue,", ["mrr", "monthly recurring revenue"]),
            ("duplicates_any_case", "MRR, mrr, Mrr", ["MRR"]),
            ("cap_on_a_long_list", ",".join(f"term {index}" for index in range(8000)), [f"term {i}" for i in range(5)]),
            ("nul_byte", "mr\x00r, arr", ["mrr", "arr"]),
        ]
    )
    def test_split_search(self, _name: str, search: str, expected: list[str]) -> None:
        assert split_search(search) == expected


class TestScoreCase(SimpleTestCase):
    @parameterized.expand(
        [
            ("sibling_below", ["weekly_active_organizations", "weekly_active_users"], 1.0, 1.0),
            ("sibling_above", ["weekly_active_users", "weekly_active_organizations"], 1.0, 0.0),
            ("expected_missing", ["weekly_active_users"], 0.0, 0.0),
        ]
    )
    def test_near_sibling_scores(self, _name: str, ranked: list[str], recall: float, sibling: float) -> None:
        case = next(case for case in SEARCH_CASES if case.name == "sibling_weekly_active_orgs")
        scores = score_case(case, ranked, confident_match=True)
        assert (scores["recall"], scores["sibling_ranked_above"]) == (recall, sibling)

    @parameterized.expand([("confident", True, 0.0), ("not_confident", False, 1.0)])
    def test_real_gap_scores_only_the_no_match_call(self, _name: str, confident: bool, expected: float) -> None:
        case = next(case for case in SEARCH_CASES if case.case_type == CaseType.REAL_GAP)
        scores = score_case(case, ["mrr"], confident_match=confident)
        assert scores == {
            "recall": None,
            "correct_no_match": expected,
            "sibling_ranked_above": None,
            "confident_when_present": None,
        }


class TestMetricListSearch(APIBaseTest):
    def setUp(self) -> None:
        super().setUp()
        self.url = f"/api/projects/{self.team.id}/data_catalog/metrics/"

    def test_search_ranks_metrics_and_says_why_each_one_matched(self) -> None:
        for name, description in [
            ("mrr", "Monthly recurring revenue from paid subscriptions."),
            ("arr", "Annual recurring revenue."),
            ("nps_score", "Net promoter score from the in-app survey."),
        ]:
            created = self.client.post(self.url, {"name": name, "description": description}, format="json")
            assert created.status_code == status.HTTP_201_CREATED, created.json()

        searched = self.client.get(self.url, {"search": "arr, subscription revenue"})
        plain = self.client.get(self.url)

        assert searched.status_code == status.HTTP_200_OK, searched.json()
        results = searched.json()["results"]
        assert [(row["name"], row["match_reason"]) for row in results] == [
            ("arr", "name match"),
            ("mrr", "all words in the description"),
        ]
        assert results[0]["is_drifted"] is False
        assert {row["match_reason"] for row in plain.json()["results"]} == {None}

    @parameterized.expand(
        [
            ("name", "mrr", "mrr", "name match"),
            ("words_in_the_description", "subscription revenue", "mrr", "all words in the description"),
            ("words_split", "mrr subscriptions", "mrr", "all words in the name and description"),
            (
                "typo_in_two_words",
                "weekly activ organisations",
                "weekly_active_organizations",
                "similar spelling to the name",
            ),
            ("one_right_word_is_not_a_typo", "active users", "weekly_active_organizations", "some words in the name"),
        ]
    )
    def test_match_reason_says_where_the_words_matched(self, _name: str, search: str, metric: str, reason: str) -> None:
        with team_scope(self.team.id):
            for name, description in [
                ("mrr", "Monthly recurring revenue from paid subscriptions."),
                ("weekly_active_organizations", "Organizations with an active member this week."),
            ]:
                Metric.objects.for_team(self.team.id).create(team=self.team, name=name, description=description)

        results = self.client.get(self.url, {"search": search}).json()["results"]

        assert {row["name"]: row["match_reason"] for row in results}[metric] == reason

    @parameterized.expand(
        [
            ("approved_only", {"status": "approved"}, ["revenue_approved"]),
            ("proposed_only", {"status": "proposed"}, ["revenue_proposed"]),
            ("hogql_only", {"definition_kind": "HogQLQuery"}, ["revenue_approved"]),
        ]
    )
    def test_search_keeps_the_list_filters(self, _name: str, filters: dict[str, str], expected: list[str]) -> None:
        with team_scope(self.team.id):
            Metric.objects.for_team(self.team.id).create(
                team=self.team,
                name="revenue_approved",
                description="Revenue.",
                status="approved",
                definition={"kind": "HogQLQuery", "query": "SELECT 1"},
            )
            Metric.objects.for_team(self.team.id).create(
                team=self.team, name="revenue_proposed", description="Revenue."
            )

        response = self.client.get(self.url, {"search": "revenue", **filters})

        assert [row["name"] for row in response.json()["results"]] == expected

    def test_search_returns_a_short_page_unless_a_limit_is_sent(self) -> None:
        with team_scope(self.team.id):
            for index in range(12):
                Metric.objects.for_team(self.team.id).create(
                    team=self.team, name=f"revenue_{index}", description="Revenue from one region."
                )

        default = self.client.get(self.url, {"search": "revenue"}).json()
        second = self.client.get(self.url, {"search": "revenue", "offset": "10"}).json()
        larger = self.client.get(self.url, {"search": "revenue", "limit": "20"}).json()

        assert (len(default["results"]), default["count"], default["next"] is not None) == (10, 12, True)
        assert (len(second["results"]), second["count"], second["next"]) == (2, 12, None)
        assert {row["name"] for row in default["results"]}.isdisjoint(row["name"] for row in second["results"])
        assert len(larger["results"]) == 12
