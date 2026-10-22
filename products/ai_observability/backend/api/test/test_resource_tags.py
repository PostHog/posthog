import json
from datetime import timedelta
from uuid import uuid4

from posthog.test.base import APIBaseTest, NonAtomicBaseTest
from unittest.mock import Mock, patch

from django.db import connection, transaction
from django.test import SimpleTestCase
from django.test.utils import CaptureQueriesContext
from django.utils import timezone

from parameterized import parameterized

from posthog.models import Tag, Team

from products.ai_observability.backend.api.resource_tags import ResourceTagFilterSerializer, ResourceTagsWriteSerializer
from products.ai_observability.backend.dataset_service import create_dataset
from products.ai_observability.backend.models.datasets import Dataset
from products.ai_observability.backend.models.offline_evaluations import OfflineExperiment
from products.ai_observability.backend.models.score_definitions import ScoreDefinition
from products.ai_observability.backend.resource_tags import ResourceTags

RESOURCES = ["datasets", "scorers", "experiments"]


class TestResourceTags(APIBaseTest):
    def setUp(self) -> None:
        super().setUp()
        self.enterContext(patch("posthog.permissions.posthog_feature_flag_enabled", return_value=True))

    def _resource(
        self, entity: str, name: str, team: Team | None = None
    ) -> Dataset | ScoreDefinition | OfflineExperiment:
        team = team or self.team
        if entity == "datasets":
            return Dataset.objects.for_team(team.id).create(team=team, name=name)
        if entity == "scorers":
            definition = ScoreDefinition.objects.create(team=team, name=name, kind="boolean")
            definition.create_new_version(config={}, created_by=self.user)
            return definition
        return OfflineExperiment.objects.for_team(team.id).create(
            id=uuid4(), team=team, name=name, started_at=timezone.now(), submission_fingerprint="a" * 64
        )

    def _url(self, entity: str) -> str:
        route = {
            "datasets": "datasets",
            "scorers": "llm_analytics/score_definitions",
            "experiments": "ai_observability/offline_experiments",
        }[entity]
        return f"/api/projects/{self.team.id}/{route}/"

    @parameterized.expand(RESOURCES)
    def test_replace_tags_and_filter_without_duplicates(self, entity: str) -> None:
        first = self._resource(entity, "First")
        second = self._resource(entity, "Second")
        self._resource(entity, "Untagged")
        url = self._url(entity)
        detail_url = f"{url}{first.pk}/"
        response = self.client.patch(detail_url, {"tags": [" Quality ", "production", "QUALITY", "a,b"]}, format="json")
        assert response.status_code == 200, response.data
        assert response.data["tags"] == ["a,b", "production", "quality"]
        response = self.client.patch(detail_url, {}, format="json")
        assert response.status_code == 200, response.data
        assert response.data["tags"] == ["a,b", "production", "quality"]
        ResourceTags.set(second, ["quality"])

        for mode, expected in (("any", {str(first.pk), str(second.pk)}), ("all", {str(first.pk)})):
            response = self.client.get(
                url, {"tags": json.dumps(["Quality", "production", "quality"]), "tag_match": mode, "limit": "1"}
            )
            assert response.status_code == 200, response.data
            assert response.data["count"] == len(expected)
            assert len(response.data["results"]) == 1
            assert str(response.data["results"][0]["id"]) in expected

        for tags, expected_count in ((["a,b"], 1), (["missing"], 0), ([], 3)):
            response = self.client.get(url, {"tags": json.dumps(tags), "tag_match": "all"})
            assert response.status_code == 200, response.data
            assert response.data["count"] == expected_count

        response = self.client.patch(detail_url, {"tags": []}, format="json")
        assert response.status_code == 200, response.data
        assert response.data["tags"] == []
        assert list(Tag.objects.filter(team=self.team).values_list("name", flat=True)) == ["quality"]
        first.refresh_from_db()
        if isinstance(first, ScoreDefinition):
            assert first.versions.count() == 1
        elif isinstance(first, Dataset):
            assert first.current_revision_id is None
        else:
            assert first.status == "uploading"

    @parameterized.expand(
        [
            ("empty", [], []),
            ("normalized", ["production", "quality"], [" Quality ", "production", "QUALITY"]),
        ]
    )
    @patch("products.ai_observability.backend.api.score_definitions.report_user_action")
    def test_saving_unchanged_scorer_tags_does_not_record_an_update(
        self, _name: str, current_tags: list[str], submitted_tags: list[str], report_user_action: Mock
    ) -> None:
        scorer = self._resource("scorers", "Tagged scorer")
        assert isinstance(scorer, ScoreDefinition)
        ResourceTags.set(scorer, current_tags)
        updated_at = timezone.now() - timedelta(days=1)
        ScoreDefinition.objects.filter(pk=scorer.pk).update(updated_at=updated_at)

        with self.captureOnCommitCallbacks(execute=True):
            response = self.client.patch(f"{self._url('scorers')}{scorer.pk}/", {"tags": submitted_tags}, format="json")

        assert response.status_code == 200, response.data
        assert response.data["tags"] == current_tags
        scorer.refresh_from_db()
        assert scorer.updated_at == updated_at
        report_user_action.assert_not_called()

    @parameterized.expand(RESOURCES)
    def test_tags_do_not_cross_projects_or_resource_types(self, entity: str) -> None:
        other_team = Team.objects.create(organization=self.organization)
        foreign = self._resource(entity, "Other project", other_team)
        ResourceTags.set(foreign, ["quality"])
        other_entity = "scorers" if entity != "scorers" else "datasets"
        ResourceTags.set(self._resource(other_entity, "Other resource"), ["quality"])
        response = self.client.get(self._url(entity), {"tags": '["quality"]'})
        assert response.status_code == 200, response.data
        assert response.data["count"] == 0
        response = self.client.patch(f"{self._url(entity)}{foreign.pk}/", {"tags": ["changed"]}, format="json")
        assert response.status_code == 404, response.data
        assert ResourceTags.names(foreign) == ["quality"]

    @parameterized.expand(RESOURCES)
    def test_listing_tags_has_constant_query_cost(self, entity: str) -> None:
        for index in range(5):
            ResourceTags.set(self._resource(entity, f"Resource {index}"), ["quality", "production"])
        url = self._url(entity)
        self.client.get(url)
        counts = []
        for limit in (1, 5):
            with CaptureQueriesContext(connection) as queries:
                response = self.client.get(url, {"limit": limit, "tags": '["quality"]'})
            assert response.status_code == 200, response.data
            assert len(response.data["results"]) == limit
            assert all(row["tags"] == ["production", "quality"] for row in response.data["results"])
            counts.append(sum('"posthog_taggeditem"' in query["sql"] for query in queries.captured_queries))
        assert counts[0] == counts[1]

    @parameterized.expand(["datasets", "scorers"])
    def test_create_tags_and_preserve_them_when_omitted(self, entity: str) -> None:
        payload: dict[str, object] = {"name": "Created with tags", "tags": [" Quality "]}
        if entity == "scorers":
            payload.update(kind="boolean", config={})
        response = self.client.post(self._url(entity), payload, format="json")
        assert response.status_code == 201, response.data
        assert response.data["tags"] == ["quality"]
        response = self.client.patch(
            f"{self._url(entity)}{response.data['id']}/", {"description": "Updated"}, format="json"
        )
        assert response.status_code == 200, response.data
        assert response.data["tags"] == ["quality"]

    @parameterized.expand(RESOURCES)
    def test_rejects_invalid_tag_filter(self, entity: str) -> None:
        response = self.client.get(self._url(entity), {"tags": "not-json"})
        assert response.status_code == 400, response.data

    @parameterized.expand(RESOURCES)
    def test_rejects_tag_names_that_exceed_the_normalized_length_limit(self, entity: str) -> None:
        resource = self._resource(entity, "Tagged resource")
        response = self.client.patch(f"{self._url(entity)}{resource.pk}/", {"tags": ["İ" * 128]}, format="json")
        assert response.status_code == 400, response.data
        assert ResourceTags.names(resource) == []


class TestResourceTagTransactions(NonAtomicBaseTest):
    def test_dataset_creation_allows_concurrent_project_foreign_key_checks(self) -> None:
        other_connection = connection.copy()
        try:
            with transaction.atomic():
                dataset = create_dataset(team=self.team, created_by=self.user, name="Tagged dataset")
                ResourceTags.set(dataset, ["quality", "production"])
                with other_connection.cursor() as cursor:
                    cursor.execute("SELECT id FROM posthog_team WHERE id = %s FOR KEY SHARE NOWAIT", [self.team.id])
                    assert cursor.fetchone() == (self.team.id,)
        finally:
            other_connection.close()


class TestResourceTagValidation(SimpleTestCase):
    @parameterized.expand(
        [
            ("blank", [" "]),
            ("too_long", ["x" * 256]),
            ("normalized_too_long", ["İ" * 128]),
            ("too_many", [str(i) for i in range(101)]),
            ("not_list", "quality"),
        ]
    )
    def test_invalid_assignments(self, _name: str, tags: object) -> None:
        serializer = ResourceTagsWriteSerializer(data={"tags": tags})
        assert not serializer.is_valid()
        assert "tags" in serializer.errors

    @parameterized.expand(
        [("invalid_json", "["), ("object", "{}"), ("too_many", json.dumps([str(i) for i in range(21)]))]
    )
    def test_invalid_filter(self, _name: str, tags: str) -> None:
        serializer = ResourceTagFilterSerializer(data={"tags": tags})
        assert not serializer.is_valid()
        assert "tags" in serializer.errors
