from posthog.test.base import APIBaseTest
from unittest.mock import MagicMock, patch

from posthog.models import OrganizationMembership, Team
from posthog.models.activity_logging.activity_log import ActivityLog
from posthog.models.activity_logging.serializers import ActivityLogSerializer

from products.ai_observability.backend.models.review_queues import ReviewQueue, ReviewQueueItem
from products.ai_observability.backend.presentation.views.trace_ids import encode_trace_id_segment


class TestAIObservabilityProjectKeys(APIBaseTest):
    def setUp(self) -> None:
        super().setUp()
        self.organization_membership.level = OrganizationMembership.Level.ADMIN
        self.organization_membership.save()
        self.project_url = f"/api/projects/{self.team.id}"

    def _issue(self, label: str, scopes: list[str]) -> dict:
        self.client.credentials()
        self.client.force_login(self.user)
        response = self.client.post(f"{self.project_url}/project_secret_api_keys/", {"label": label, "scopes": scopes})
        assert response.status_code == 201, response.data
        assert response.data["scopes"] == scopes
        return response.data

    def _use(self, key: dict) -> None:
        self.client.logout()
        self.client.credentials(HTTP_AUTHORIZATION=f"Bearer {key['value']}")

    def test_scorer_and_trace_score_share_project_grants(self) -> None:
        writer = self._issue("Review writer", ["llm_analytics:write"])
        reader = self._issue("Review reader", ["llm_analytics:read"])
        self._use(writer)
        scorers = f"{self.project_url}/llm_analytics/score_definitions/"
        reviews = f"{self.project_url}/llm_analytics/trace_reviews/"
        definition = self.client.post(
            scorers,
            {"name": "Accurate", "kind": "boolean", "config": {"true_label": "Yes", "false_label": "No"}},
            format="json",
        )
        assert definition.status_code == 201, definition.data
        assert definition.data["created_by"] is None
        assert definition.data["created_by_project_key_id"] == writer["id"]
        assert definition.data["updated_by_project_key_id"] == writer["id"]
        assert (
            ActivityLog.objects.get(
                team_id=self.team.id, scope="ScoreDefinition", item_id=definition.data["id"], activity="created"
            ).credential_id
            == writer["id"]
        )
        trace_id = "scored-trace"
        queue = ReviewQueue.objects.create(team=self.team, name="Ready to review")
        pending = ReviewQueueItem.objects.create(team=self.team, queue=queue, trace_id=trace_id)
        review = self.client.post(
            reviews,
            {"trace_id": trace_id, "scores": [{"definition_id": definition.data["id"], "boolean_value": True}]},
            format="json",
        )
        assert review.status_code == 201, review.data
        assert review.data["created_by"] is None
        assert review.data["reviewed_by"] is None
        assert review.data["reviewed_by_project_key_id"] == writer["id"]
        audit = ActivityLog.objects.filter(
            team_id=self.team.id, scope="TraceReview", item_id=review.data["id"]
        ).order_by("created_at")
        url = f"{reviews}{review.data['id']}/"
        self._use(reader)
        assert definition.data["id"] in [scorer["id"] for scorer in self.client.get(scorers).data["results"]]
        assert self.client.get(url).data["scores"][0]["boolean_value"] is True
        rendered = self.client.get(
            f"{self.project_url}/ai_observability/traces/{encode_trace_id_segment(trace_id)}/review/"
        )
        assert rendered.status_code == 200, rendered.data
        assert rendered.data["review"]["reviewedBy"] == f"Project key · {writer['id'][-8:]}"
        denied = self.client.delete(url)
        assert denied.status_code == 403
        assert "llm_analytics:write" in denied.data["detail"]
        other_team = Team.objects.create(organization=self.organization, name="Other project")
        assert self.client.get(f"/api/projects/{other_team.id}/llm_analytics/trace_reviews/").status_code == 403
        assert self.client.get(f"{self.project_url}/ai_observability/offline_experiments/").status_code == 403
        self._use(writer)
        assert self.client.delete(url).status_code == 204
        assert self.client.delete(url).status_code == 404
        assert list(audit.values_list("activity", "credential_type", "credential_id", "is_system")) == [
            ("created", "project_secret_key", writer["id"], False),
            ("deleted", "project_secret_key", writer["id"], False),
        ]
        created = audit.get(activity="created")
        assert ActivityLogSerializer(created).data["user"]["first_name"] == f"Project key {writer['id']}"
        assert created.detail is not None
        assert [(change["field"], change["before"]) for change in created.detail["changes"]] == [
            ("pending_queue_item", str(pending.pk))
        ]

    def test_project_key_scorer_edits_attribute_metadata_and_immutable_versions(self) -> None:
        key = self._issue("Scorer editor", ["llm_analytics:write"])
        scorers = f"{self.project_url}/llm_analytics/score_definitions/"
        config = {"true_label": "Yes", "false_label": "No"}
        original = self.client.post(scorers, {"name": "Relevant", "kind": "boolean", "config": config}, format="json")
        assert original.status_code == 201, original.data
        url = f"{scorers}{original.data['id']}/"
        logs = ActivityLog.objects.filter(team_id=self.team.id, scope="ScoreDefinition", item_id=original.data["id"])
        self._use(key)
        for _ in range(2):
            edited = self.client.patch(url, {"archived": True}, format="json")
            assert edited.status_code == 200, edited.data
            assert edited.data["updated_by"] is None
            assert edited.data["updated_by_project_key_id"] == key["id"]
        edit = logs.get()
        assert edit.detail is not None
        assert {change["field"]: change.get("before") for change in edit.detail["changes"]} == {
            "archived": None,
            "updated_by": self.user.id,
        }
        version = self.client.post(
            url + "new_version/", {"config": config, "base_version": 1, "name": "Relevance"}, format="json"
        )
        assert version.status_code == 200, version.data
        assert version.data["updated_by_project_key_id"] == key["id"]
        history = self.client.get(url + "versions/").data["results"]
        assert [(row["version"], row["created_by_project_key_id"]) for row in history] == [(2, key["id"]), (1, None)]
        assert list(logs.values_list("credential_id", flat=True)) == [key["id"], key["id"]]
        self.client.credentials()
        self.client.force_login(self.user)
        human = self.client.patch(url, {"archived": False}, format="json")
        assert human.status_code == 200, human.data
        assert human.data["updated_by"]["id"] == self.user.id
        assert human.data["updated_by_project_key_id"] is None

    def test_project_key_delete_and_recreate_records_the_displaced_reviewer(self) -> None:
        key = self._issue("Review writer", ["llm_analytics:write"])
        reviews = f"{self.project_url}/llm_analytics/trace_reviews/"
        original = self.client.post(reviews, {"trace_id": "replacement"}, format="json")
        assert original.status_code == 201
        self._use(key)
        assert self.client.delete(f"{reviews}{original.data['id']}/").status_code == 204
        replacement = self.client.post(reviews, {"trace_id": "replacement"}, format="json")
        assert replacement.status_code == 201
        audit = ActivityLog.objects.filter(team_id=self.team.id, scope="TraceReview", credential_id=key["id"])
        deleted = audit.get(item_id=original.data["id"], activity="deleted")
        assert deleted.detail is not None
        assert [(change["field"], change["before"]) for change in deleted.detail["changes"]] == [
            ("reviewed_by", self.user.id)
        ]
        assert audit.get(item_id=replacement.data["id"], activity="created").is_system is False
        other_key = self._issue("Review cleanup", ["llm_analytics:write"])
        self._use(other_key)
        assert self.client.delete(f"{reviews}{replacement.data['id']}/").status_code == 204
        deleted = ActivityLog.objects.get(
            team_id=self.team.id, scope="TraceReview", item_id=replacement.data["id"], activity="deleted"
        )
        assert deleted.credential_id == other_key["id"]
        assert deleted.detail is not None
        assert [(change["field"], change["before"]) for change in deleted.detail["changes"]] == [
            ("reviewed_by_project_key_id", key["id"])
        ]

    def test_project_key_edits_preserve_the_human_reviewer_on_retries_and_audit_real_changes(self) -> None:
        key = self._issue("Review editor", ["llm_analytics:write"])
        scorer = self.client.post(
            f"{self.project_url}/llm_analytics/score_definitions/",
            {"name": "Resolved", "kind": "boolean", "config": {"true_label": "Yes", "false_label": "No"}},
            format="json",
        )
        assert scorer.status_code == 201, scorer.data
        score = {"definition_id": scorer.data["id"], "boolean_value": True}
        reviews = f"{self.project_url}/llm_analytics/trace_reviews/"
        original = self.client.post(
            reviews, {"trace_id": "reviewed", "comment": "Human review", "scores": [score]}, format="json"
        )
        assert original.status_code == 201, original.data
        url = f"{reviews}{original.data['id']}/"
        queue = ReviewQueue.objects.create(team=self.team, name="Pending reviews")
        pending = ReviewQueueItem.objects.create(team=self.team, queue=queue, trace_id="reviewed")
        self._use(key)
        logs = ActivityLog.objects.filter(team_id=self.team.id, scope="TraceReview", item_id=original.data["id"])
        other_queue = ReviewQueue.objects.create(team=self.team, name="Another queue")
        same = self.client.patch(url, {"queue_id": str(other_queue.pk)}, format="json")
        assert same.status_code == 200, same.data
        assert ReviewQueueItem.objects.filter(team=self.team, pk=pending.pk, deleted=False).exists()
        assert not logs.exists()
        for payload in ({}, {"comment": "Human review", "scores": [score]}):
            same = self.client.patch(url, payload, format="json")
            assert same.status_code == 200, same.data
            assert same.data == original.data
        pending.refresh_from_db()
        assert pending.deleted
        removal = logs.get()
        assert removal.activity == "updated"
        assert removal.credential_id == key["id"]
        assert removal.detail is not None
        assert [(change["field"], change["before"]) for change in removal.detail["changes"]] == [
            ("pending_queue_item", str(pending.pk))
        ]

        requeued = ReviewQueueItem.objects.create(team=self.team, queue=queue, trace_id="reviewed")
        edited = self.client.patch(
            url, {"comment": "Revised", "scores": [{**score, "boolean_value": False}]}, format="json"
        )
        assert edited.status_code == 200, edited.data
        assert edited.data["reviewed_by"] is None
        assert edited.data["reviewed_by_project_key_id"] == key["id"]
        assert edited.data["scores"][0]["boolean_value"] is False
        log = logs.exclude(pk=removal.pk).get()
        assert log.credential_type == "project_secret_key"
        assert log.credential_id == key["id"]
        assert log.detail is not None
        assert {change["field"]: change.get("before") for change in log.detail["changes"]} == {
            "comment": None,
            "scores": None,
            "reviewed_by": self.user.id,
            "pending_queue_item": str(requeued.pk),
        }

        self.client.credentials()
        self.client.force_login(self.user)
        human_edit = self.client.patch(url, {"comment": "Reviewed again"}, format="json")
        assert human_edit.status_code == 200, human_edit.data
        assert human_edit.data["reviewed_by"]["id"] == self.user.id
        assert human_edit.data["reviewed_by_project_key_id"] is None
        human_log = logs.get(user=self.user, activity="updated")
        assert human_log.detail is not None
        assert [(change["field"], change["before"]) for change in human_log.detail["changes"]] == [
            ("reviewed_by_project_key_id", key["id"])
        ]

    def test_audit_identifies_the_previous_project_key_reviewer(self) -> None:
        original_key = self._issue("First reviewer", ["llm_analytics:write"])
        other_key = self._issue("Second reviewer", ["llm_analytics:write"])
        self._use(original_key)
        reviews = f"{self.project_url}/llm_analytics/trace_reviews/"
        review = self.client.post(reviews, {"trace_id": "key-authored", "comment": "First review"}, format="json")
        assert review.status_code == 201, review.data
        url = f"{reviews}{review.data['id']}/"
        logs = ActivityLog.objects.filter(team_id=self.team.id, scope="TraceReview", item_id=review.data["id"])
        self._use(other_key)
        retry = self.client.patch(url, {"comment": "First review"}, format="json")
        assert retry.status_code == 200, retry.data
        assert retry.data["reviewed_by_project_key_id"] == original_key["id"]
        assert not logs.filter(activity="updated").exists()

        edited = self.client.patch(url, {"comment": "Second review"}, format="json")
        assert edited.status_code == 200, edited.data
        assert edited.data["reviewed_by_project_key_id"] == other_key["id"]
        edit = logs.get(activity="updated", credential_id=other_key["id"])
        assert edit.detail is not None
        assert {change["field"]: change.get("before") for change in edit.detail["changes"]} == {
            "comment": None,
            "reviewed_by_project_key_id": original_key["id"],
        }

        self.client.credentials()
        self.client.force_login(self.user)
        assert self.client.delete(url).status_code == 204
        deleted = logs.get(activity="deleted", user=self.user)
        assert deleted.detail is not None
        assert [(change["field"], change["before"]) for change in deleted.detail["changes"]] == [
            ("reviewed_by_project_key_id", other_key["id"])
        ]

    @patch("posthog.permissions.posthog_feature_flag_enabled", return_value=True)
    def test_dataset_history_identifies_the_writer_of_each_version(self, _flag: MagicMock) -> None:
        creator = self._issue("Dataset creator", ["dataset:write"])
        editor = self._issue("Dataset editor", ["dataset:write"])
        datasets = f"{self.project_url}/datasets/"
        items = f"{self.project_url}/dataset_items/"
        self._use(creator)
        dataset = self.client.post(datasets, {"name": "Answer quality"})
        assert dataset.status_code == 201, dataset.data
        assert dataset.data["created_by"] is None
        assert dataset.data["created_by_project_key_id"] == creator["id"]
        item = self.client.post(items, {"dataset": dataset.data["id"], "input": "First item"}, format="json")
        assert item.status_code == 201, item.data
        url = f"{items}{item.data['id']}/"
        self._use(editor)
        assert self.client.patch(url, {"base_version": 1, "input": "Edited"}, format="json").status_code == 200
        assert self.client.post(url + "archive/", {"base_version": 2}, format="json").status_code == 200
        self._use(creator)
        assert self.client.post(url + "restore/", {"base_version": 3}, format="json").status_code == 200
        self.client.credentials()
        self.client.force_login(self.user)
        assert self.client.patch(url, {"base_version": 4, "input": "Final"}, format="json").status_code == 200

        history = self.client.get(url + "versions/").data["results"]
        revisions = self.client.get(f"{datasets}{dataset.data['id']}/revisions/").data["results"]
        expected_actors = [
            (5, self.user.id, None),
            (4, None, creator["id"]),
            (3, None, editor["id"]),
            (2, None, editor["id"]),
            (1, None, creator["id"]),
        ]
        assert [
            (
                row["version"],
                row["version_created_by"] and row["version_created_by"]["id"],
                row["version_created_by_project_key_id"],
            )
            for row in history
        ] == expected_actors
        assert [
            (row["revision"], row["created_by"] and row["created_by"]["id"], row["created_by_project_key_id"])
            for row in revisions
        ] == expected_actors
        assert all(row["created_by"] is None and row["created_by_project_key_id"] == creator["id"] for row in history)

    @patch("posthog.permissions.posthog_feature_flag_enabled", return_value=True)
    def test_dataset_access_controls_keep_their_existing_key_scopes(self, _flag: MagicMock) -> None:
        project_key = self._issue("Dataset writer", ["dataset:write"])
        dataset = self.client.post(f"{self.project_url}/datasets/", {"name": "Shared dataset"})
        assert dataset.status_code == 201, dataset.data
        url = f"{self.project_url}/datasets/{dataset.data['id']}/"
        access_controls = url + "access_controls/"
        self._use(project_key)
        assert self.client.get(access_controls).status_code == 403

        reader = self.create_personal_api_key_with_scopes(["access_control:read"])
        self.client.credentials(HTTP_AUTHORIZATION=f"Bearer {reader}")
        assert self.client.get(access_controls).status_code == 200
        assert self.client.get(url + "users_with_access/").status_code == 200
        rule = {"organization_member": str(self.organization_membership.id), "access_level": "viewer"}
        assert self.client.put(access_controls, rule, format="json").status_code == 403
        writer = self.create_personal_api_key_with_scopes(["access_control:write"])
        self.client.credentials(HTTP_AUTHORIZATION=f"Bearer {writer}")
        updated = self.client.put(access_controls, rule, format="json")
        assert updated.status_code == 200, updated.data

    def test_project_keys_can_read_dataset_snapshots_but_exports_require_a_user(self) -> None:
        writer = self._issue("Dataset writer", ["dataset:write"])
        reader = self._issue("Dataset reader", ["dataset:read"])
        self._use(writer)
        datasets = f"{self.project_url}/datasets/"
        items = f"{self.project_url}/dataset_items/"
        with patch("posthog.permissions.posthog_feature_flag_enabled", return_value=True):
            dataset = self.client.post(datasets, {"name": "Project key dataset"})
            assert dataset.status_code == 201, dataset.data
            dataset_id = dataset.data["id"]
            retention_url = f"{datasets}{dataset_id}/extend_retention/"
            assert self.client.post(retention_url, {}, format="json").status_code == 200
            item = self.client.post(items, {"dataset": dataset_id, "input": "First item"}, format="json")
            assert item.status_code == 201, item.data
            self._use(reader)
            assert self.client.get(datasets + "retention/").status_code == 200
            denied = self.client.post(retention_url, {}, format="json")
            assert denied.status_code == 403
            assert "dataset:write" in denied.data["detail"]
            assert self.client.post(datasets, {"name": "Read only"}).status_code == 403
            snapshot = self.client.get(items, {"dataset": dataset_id, "revision": item.data["dataset_revision"]})
            assert snapshot.status_code == 200, snapshot.data
            assert snapshot.data["results"][0]["id"] == item.data["id"]
            exports = f"{datasets}{dataset_id}/exports/"
            self.client.logout()
            personal_key = self.create_personal_api_key_with_scopes(["dataset:read"])
            self.client.credentials(HTTP_AUTHORIZATION=f"Bearer {personal_key}")
            assert self.client.post(retention_url, {}, format="json").status_code == 200
            receipt = self.client.post(exports, {}, format="json")
            assert receipt.status_code == 201, receipt.data
            url = f"{exports}{receipt.data['id']}/"
            assert self.client.get(url).status_code == 200
            for key in (reader, writer):
                self._use(key)
                assert self.client.post(exports, {}, format="json").status_code == 403
                assert self.client.get(url).status_code == 403
                assert self.client.get(f"{url}content/").status_code == 403
