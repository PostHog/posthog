from posthog.test.base import APIBaseTest, BaseTest

from django.test import SimpleTestCase

from parameterized import parameterized
from rest_framework import status

from posthog.models.personal_api_key import PersonalAPIKey
from posthog.models.scoping import team_scope
from posthog.models.utils import generate_random_token_personal, hash_key_value

from products.data_catalog.backend.logic.metric_search import search_metrics
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


class TestMetricSearchAPI(APIBaseTest):
    def setUp(self) -> None:
        super().setUp()
        self.url = f"/api/projects/{self.team.id}/data_catalog/metric_search/"

    def test_metric_created_through_the_api_is_searchable(self) -> None:
        created = self.client.post(
            f"/api/projects/{self.team.id}/data_catalog/metrics/",
            {"name": "mrr", "description": "Monthly recurring revenue from paid subscriptions."},
            format="json",
        )
        assert created.status_code == status.HTTP_201_CREATED, created.json()

        response = self.client.post(self.url, {"query": ["subscription revenue", "sandbox"]}, format="json")

        assert response.status_code == status.HTTP_200_OK, response.json()
        body = response.json()
        assert [hit["name"] for hit in body["results"]] == ["mrr"]
        assert body["results"][0]["match_reason"] == "description match"
        assert body["results"][0]["is_drifted"] is False
        assert body["confident_match"] is True
        assert body["search_mode"] == "lexical"

    @parameterized.expand(
        [
            ("read_scope", ["data_catalog:read"], status.HTTP_200_OK),
            ("other_scope", ["insight:read"], status.HTTP_403_FORBIDDEN),
        ]
    )
    def test_search_needs_only_the_read_scope(self, _name: str, scopes: list[str], expected: int) -> None:
        raw = generate_random_token_personal()
        PersonalAPIKey.objects.create(label="k", user=self.user, secure_value=hash_key_value(raw), scopes=scopes)
        self.client.logout()
        response = self.client.post(self.url, {"query": ["mrr"]}, format="json", HTTP_AUTHORIZATION=f"Bearer {raw}")
        assert response.status_code == expected, response.json()
