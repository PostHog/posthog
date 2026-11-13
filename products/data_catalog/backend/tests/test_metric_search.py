from posthog.test.base import APIBaseTest, BaseTest
from unittest.mock import MagicMock, patch

from django.db import connection
from django.db.models import QuerySet
from django.test import SimpleTestCase
from django.test.utils import CaptureQueriesContext

from parameterized import parameterized
from rest_framework import status

from posthog.api.embedding_worker import EmbeddingResponse
from posthog.models.scoping import team_scope

from products.data_catalog.backend.logic.metric_embeddings import (
    METRIC_EMBEDDING_MODEL,
    RefreshOutcome,
    metric_search_text,
    refresh_metric_embedding,
    search_text_hash,
)
from products.data_catalog.backend.logic.metric_search import search_metrics, split_search
from products.data_catalog.backend.logic.metrics import metrics_for_team, update_metric, upsert_metric
from products.data_catalog.backend.models import Metric
from products.data_catalog.evals.metric_search_cases import LEXICAL_CASE_TYPES, SEARCH_CASES, CaseType, SearchCase
from products.data_catalog.evals.metric_search_runner import LEXICAL, run_case, score_case, seed_metric_search_catalog

_GENERATE_EMBEDDING = "products.data_catalog.backend.logic.metric_embeddings.generate_embedding"
_FLAG = "products.data_catalog.backend.logic.metric_embeddings.posthoganalytics.feature_enabled"


def _cases(*case_types: CaseType) -> list[tuple[str, SearchCase]]:
    return [(case.name, case) for case in SEARCH_CASES if case.case_type in case_types]


def _embedding(vector: list[float]) -> EmbeddingResponse:
    return EmbeddingResponse(embedding=vector, tokens_used=10, did_truncate=False)


def _store_vector(candidates: QuerySet[Metric], name: str, vector: list[float], text_hash: str | None = None) -> None:
    metric = candidates.get(name=name)
    candidates.filter(name=name).update(
        embedding=vector,
        embedding_model=METRIC_EMBEDDING_MODEL,
        embedding_text_hash=text_hash or search_text_hash(metric_search_text(metric)),
    )


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

    def test_semantic_lane_adds_a_hit_and_falls_back_when_embedding_fails(self) -> None:
        with team_scope(self.team.id):
            candidates = Metric.objects.for_team(self.team.id).filter(deleted=False)
            _store_vector(candidates, "nps_score", [1.0, 0.0])
            _store_vector(candidates, "mrr", [0.0, 1.0])
            _store_vector(candidates, "arr", [0.95, 0.05], text_hash="stale")

            hybrid = search_metrics(candidates, ["loyalty"], embed_query=lambda _text: [0.9, 0.1])
            fallback = search_metrics(candidates, ["loyalty"], embed_query=lambda _text: None)

        assert [hit.metric.name for hit in hybrid.hits] == ["nps_score", "mrr"], "arr's vector is stale"
        assert all(hit.match_reason.startswith("similar meaning") for hit in hybrid.hits)
        assert hybrid.confident_match is True
        assert hybrid.search_mode == "hybrid"
        assert fallback.hits == []
        assert fallback.search_mode == "lexical"

    def test_weak_word_matches_in_both_lanes_do_not_push_down_the_closest_semantic_hit(self) -> None:
        with team_scope(self.team.id):
            candidates = Metric.objects.for_team(self.team.id).filter(
                deleted=False, name__in=["nps_score", "api_error_rate", "logo_churn_rate"]
            )
            for name, vector in [
                ("nps_score", [1.0, 0.0]),
                ("api_error_rate", [0.7, 0.3]),
                ("logo_churn_rate", [0.6, 0.4]),
            ]:
                _store_vector(candidates, name, vector)

            result = search_metrics(candidates, ["loyalty rating"], embed_query=lambda _text: [1.0, 0.0])

        ranked = [hit.metric.name for hit in result.hits]
        assert set(ranked) == {"nps_score", "api_error_rate", "logo_churn_rate"}
        assert ranked.index("nps_score") <= 1, ranked

    def test_semantic_lane_reads_every_vector_in_one_query(self) -> None:
        def queries_for_one_search(candidates: QuerySet[Metric]) -> int:
            with CaptureQueriesContext(connection) as queries:
                search_metrics(candidates, ["loyalty"], embed_query=lambda _text: [1.0, 0.0])
            return len(queries.captured_queries)

        with team_scope(self.team.id):
            candidates = metrics_for_team(self.team)
            _store_vector(candidates, "nps_score", [1.0, 0.0])
            with_one_vector = queries_for_one_search(candidates)
            for name in ("mrr", "arr", "logo_churn_rate"):
                _store_vector(candidates, name, [0.5, 0.5])
            with_four_vectors = queries_for_one_search(candidates)

        assert with_four_vectors == with_one_vector

    def test_confident_word_matches_rank_above_meaning_only_hits(self) -> None:
        with team_scope(self.team.id):
            candidates = Metric.objects.for_team(self.team.id).filter(
                deleted=False, name__in=["mrr", "arr", "nps_score"]
            )
            for name, vector in [("mrr", [0.0, 1.0]), ("arr", [0.0, 1.0]), ("nps_score", [1.0, 0.0])]:
                _store_vector(candidates, name, vector)

            result = search_metrics(candidates, ["recurring revenue"], embed_query=lambda _text: [1.0, 0.0])

        assert [hit.metric.name for hit in result.hits][-1] == "nps_score", [hit.match_reason for hit in result.hits]


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


@patch(_GENERATE_EMBEDDING, return_value=_embedding([0.1, 0.2]))
class TestMetricEmbeddingRefresh(BaseTest):
    def setUp(self) -> None:
        super().setUp()
        self.organization.is_ai_data_processing_approved = True
        self.organization.save()

    def _stored(self, name: str) -> Metric:
        return Metric.objects.for_team(self.team.id).get(name=name)

    def test_write_embeds_only_when_the_search_text_changes(self, generate: MagicMock) -> None:
        with self.captureOnCommitCallbacks(execute=True):
            upsert_metric(team=self.team, user=self.user, name="mrr", description="Monthly revenue")
        metric = self._stored("mrr")
        assert metric.embedding == [0.1, 0.2]
        assert generate.call_args.args[1] == metric_search_text(metric)

        with self.captureOnCommitCallbacks(execute=True):
            update_metric(metric, team=self.team, user=self.user, owner=None)
        with self.captureOnCommitCallbacks(execute=True):
            update_metric(self._stored("mrr"), team=self.team, user=self.user, description="Monthly revenue")
        assert generate.call_count == 1
        assert self._stored("mrr").embedding == [0.1, 0.2]

        generate.return_value = _embedding([0.3, 0.4])
        with self.captureOnCommitCallbacks(execute=True):
            update_metric(
                self._stored("mrr"), team=self.team, user=self.user, description="Monthly subscription revenue"
            )
        assert generate.call_count == 2
        assert self._stored("mrr").embedding == [0.3, 0.4]

    def test_edit_during_the_embedding_call_drops_the_old_vector(self, generate: MagicMock) -> None:
        with team_scope(self.team.id):
            Metric.objects.for_team(self.team.id).create(team=self.team, name="mrr", description="Monthly revenue")
        metric = self._stored("mrr")

        def edit_while_embedding(*_args: object, **_kwargs: object) -> EmbeddingResponse:
            Metric.objects.for_team(self.team.id).filter(pk=metric.pk).update(description="Monthly recurring revenue")
            return _embedding([0.9, 0.1])

        generate.side_effect = edit_while_embedding
        refresh = refresh_metric_embedding(metric)

        assert refresh.outcome == RefreshOutcome.CHANGED
        assert self._stored("mrr").embedding is None

    def test_org_without_ai_approval_is_never_embedded(self, generate: MagicMock) -> None:
        self.organization.is_ai_data_processing_approved = False
        self.organization.save()
        with self.captureOnCommitCallbacks(execute=True):
            upsert_metric(team=self.team, user=self.user, name="mrr", description="Monthly revenue")
        generate.assert_not_called()
        assert self._stored("mrr").embedding is None


@patch(_FLAG, return_value=False)
class TestMetricListSearch(APIBaseTest):
    def setUp(self) -> None:
        super().setUp()
        self.url = f"/api/projects/{self.team.id}/data_catalog/metrics/"

    def test_search_ranks_metrics_and_says_why_each_one_matched(self, _flag: MagicMock) -> None:
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

    def test_flag_on_adds_meaning_hits_and_falls_back_to_words_when_embedding_fails(self, flag: MagicMock) -> None:
        flag.return_value = True
        self.organization.is_ai_data_processing_approved = True
        self.organization.save()
        with team_scope(self.team.id):
            for name, description in [
                ("nps_score", "Net promoter score from the in-app survey."),
                ("mrr", "Monthly recurring revenue."),
            ]:
                Metric.objects.for_team(self.team.id).create(team=self.team, name=name, description=description)
            candidates = Metric.objects.for_team(self.team.id).all()
            _store_vector(candidates, "nps_score", [1.0, 0.0])
            _store_vector(candidates, "mrr", [0.0, 1.0])

        with patch(_GENERATE_EMBEDDING, return_value=_embedding([1.0, 0.0])):
            meaning = self.client.get(self.url, {"search": "loyalty"}).json()["results"]
        with patch(_GENERATE_EMBEDDING, side_effect=TimeoutError):
            fallback = self.client.get(self.url, {"search": "loyalty, revenue"}).json()["results"]

        assert (meaning[0]["name"], meaning[0]["match_reason"]) == ("nps_score", "similar meaning (1.00)")
        assert [(row["name"], row["match_reason"]) for row in fallback] == [("mrr", "all words in the description")]

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
    def test_match_reason_says_where_the_words_matched(
        self, _flag: MagicMock, _name: str, search: str, metric: str, reason: str
    ) -> None:
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
    def test_search_keeps_the_list_filters(
        self, _flag: MagicMock, _name: str, filters: dict[str, str], expected: list[str]
    ) -> None:
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

    def test_search_returns_a_short_page_unless_a_limit_is_sent(self, _flag: MagicMock) -> None:
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
