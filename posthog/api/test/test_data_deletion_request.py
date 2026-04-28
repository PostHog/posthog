from datetime import timedelta

from posthog.test.base import APIBaseTest
from unittest.mock import patch

from django.utils import timezone

from rest_framework import status

from posthog.models.data_deletion_request import DataDeletionRequest, RequestStatus, RequestType
from posthog.models.organization import OrganizationMembership


class TestDataDeletionRequestAPI(APIBaseTest):
    def setUp(self) -> None:
        super().setUp()
        self.organization_membership.level = OrganizationMembership.Level.ADMIN
        self.organization_membership.save()
        self._flag_patcher = patch("posthog.api.data_deletion_request._user_can_self_serve", return_value=True)
        self._flag_patcher.start()

    def tearDown(self) -> None:
        self._flag_patcher.stop()
        super().tearDown()

    def _url(self, suffix: str = "") -> str:
        return f"/api/environments/{self.team.pk}/data_deletion_requests{suffix}"

    def _valid_payload(self, **overrides):
        start = timezone.now() - timedelta(days=2)
        end = timezone.now() - timedelta(days=1)
        payload = {
            "request_type": RequestType.EVENT_REMOVAL.value,
            "start_time": start.isoformat(),
            "end_time": end.isoformat(),
            "events": ["$pageview"],
            "delete_all_events": False,
            "hogql_predicate": "",
            "properties": [],
            "notes": "bulk cleanup",
        }
        payload.update(overrides)
        return payload

    # --- Feature flag gating -------------------------------------------------

    def test_endpoint_hidden_when_flag_off(self) -> None:
        self._flag_patcher.stop()
        try:
            with patch("posthog.api.data_deletion_request._user_can_self_serve", return_value=False):
                response = self.client.get(self._url("/"))
                assert response.status_code == status.HTTP_404_NOT_FOUND
                response = self.client.post(self._url("/"), self._valid_payload(), format="json")
                assert response.status_code == status.HTTP_404_NOT_FOUND
        finally:
            self._flag_patcher.start()

    # --- Permission gating ---------------------------------------------------

    def test_non_admin_cannot_create(self) -> None:
        self.organization_membership.level = OrganizationMembership.Level.MEMBER
        self.organization_membership.save()
        response = self.client.post(self._url("/"), self._valid_payload(), format="json")
        assert response.status_code == status.HTTP_403_FORBIDDEN

    def test_non_admin_can_list(self) -> None:
        self.organization_membership.level = OrganizationMembership.Level.MEMBER
        self.organization_membership.save()
        response = self.client.get(self._url("/"))
        assert response.status_code == status.HTTP_200_OK

    # --- Creation ------------------------------------------------------------

    def test_create_lands_in_pending(self) -> None:
        response = self.client.post(self._url("/"), self._valid_payload(), format="json")
        assert response.status_code == status.HTTP_201_CREATED, response.json()
        data = response.json()
        assert data["status"] == RequestStatus.PENDING
        assert data["created_by"]["id"] == self.user.id
        request = DataDeletionRequest.objects.get(id=data["id"])
        assert request.team_id == self.team.pk
        assert request.created_by_staff is False
        assert request.requires_approval is True

    def test_person_removal_is_rejected(self) -> None:
        response = self.client.post(
            self._url("/"),
            self._valid_payload(request_type=RequestType.PERSON_REMOVAL.value),
            format="json",
        )
        assert response.status_code == status.HTTP_400_BAD_REQUEST
        assert response.json()["attr"] == "request_type"

    def test_property_removal_requires_properties(self) -> None:
        response = self.client.post(
            self._url("/"),
            self._valid_payload(
                request_type=RequestType.PROPERTY_REMOVAL.value,
                properties=[],
            ),
            format="json",
        )
        assert response.status_code == status.HTTP_400_BAD_REQUEST

    def test_event_removal_requires_scope(self) -> None:
        response = self.client.post(
            self._url("/"),
            self._valid_payload(events=[], delete_all_events=False, hogql_predicate=""),
            format="json",
        )
        assert response.status_code == status.HTTP_400_BAD_REQUEST

    def test_end_time_must_be_after_start_time(self) -> None:
        now = timezone.now()
        response = self.client.post(
            self._url("/"),
            self._valid_payload(
                start_time=now.isoformat(),
                end_time=(now - timedelta(hours=1)).isoformat(),
            ),
            format="json",
        )
        assert response.status_code == status.HTTP_400_BAD_REQUEST

    def test_invalid_hogql_predicate_is_rejected(self) -> None:
        response = self.client.post(
            self._url("/"),
            self._valid_payload(hogql_predicate="this is not valid HogQL at all ~~"),
            format="json",
        )
        assert response.status_code == status.HTTP_400_BAD_REQUEST

    # --- Listing -------------------------------------------------------------

    def test_list_is_team_scoped(self) -> None:
        DataDeletionRequest.objects.create(
            team_id=self.team.pk,
            request_type=RequestType.EVENT_REMOVAL,
            start_time=timezone.now() - timedelta(days=2),
            end_time=timezone.now() - timedelta(days=1),
            events=["$pageview"],
            status=RequestStatus.PENDING,
            created_by=self.user,
        )
        DataDeletionRequest.objects.create(
            team_id=self.team.pk + 9999,
            request_type=RequestType.EVENT_REMOVAL,
            start_time=timezone.now() - timedelta(days=2),
            end_time=timezone.now() - timedelta(days=1),
            events=["$pageview"],
            status=RequestStatus.PENDING,
        )
        response = self.client.get(self._url("/"))
        assert response.status_code == status.HTTP_200_OK
        ids = [row["id"] for row in response.json()["results"]]
        assert len(ids) == 1

    def test_list_excludes_person_removal(self) -> None:
        DataDeletionRequest.objects.create(
            team_id=self.team.pk,
            request_type=RequestType.PERSON_REMOVAL,
            start_time=timezone.now() - timedelta(days=2),
            end_time=timezone.now() - timedelta(days=1),
            events=[],
            status=RequestStatus.PENDING,
            person_drop_profiles=True,
            created_by=self.user,
        )
        response = self.client.get(self._url("/"))
        assert response.status_code == status.HTTP_200_OK
        assert response.json()["results"] == []

    # --- Cancel / destroy ---------------------------------------------------

    def test_cancel_pending_request(self) -> None:
        instance = DataDeletionRequest.objects.create(
            team_id=self.team.pk,
            request_type=RequestType.EVENT_REMOVAL,
            start_time=timezone.now() - timedelta(days=2),
            end_time=timezone.now() - timedelta(days=1),
            events=["$pageview"],
            status=RequestStatus.PENDING,
            created_by=self.user,
        )
        response = self.client.delete(self._url(f"/{instance.pk}"))
        assert response.status_code == status.HTTP_204_NO_CONTENT
        assert not DataDeletionRequest.objects.filter(pk=instance.pk).exists()

    def test_cannot_cancel_approved_request(self) -> None:
        instance = DataDeletionRequest.objects.create(
            team_id=self.team.pk,
            request_type=RequestType.EVENT_REMOVAL,
            start_time=timezone.now() - timedelta(days=2),
            end_time=timezone.now() - timedelta(days=1),
            events=["$pageview"],
            status=RequestStatus.APPROVED,
            approved=True,
            approved_at=timezone.now(),
            created_by=self.user,
        )
        response = self.client.delete(self._url(f"/{instance.pk}"))
        assert response.status_code == status.HTTP_409_CONFLICT
        assert DataDeletionRequest.objects.filter(pk=instance.pk).exists()

    # --- Preview -------------------------------------------------------------

    def test_preview_validates_time_range(self) -> None:
        now = timezone.now()
        response = self.client.post(
            self._url("/preview/"),
            {
                "request_type": RequestType.EVENT_REMOVAL.value,
                "start_time": now.isoformat(),
                "end_time": (now - timedelta(hours=1)).isoformat(),
                "events": ["$pageview"],
            },
            format="json",
        )
        assert response.status_code == status.HTTP_400_BAD_REQUEST

    def test_preview_requires_scoping_criterion(self) -> None:
        response = self.client.post(
            self._url("/preview/"),
            {
                "request_type": RequestType.EVENT_REMOVAL.value,
                "start_time": (timezone.now() - timedelta(days=2)).isoformat(),
                "end_time": (timezone.now() - timedelta(days=1)).isoformat(),
                "events": [],
                "delete_all_events": False,
                "hogql_predicate": "",
            },
            format="json",
        )
        assert response.status_code == status.HTTP_400_BAD_REQUEST

    def test_preview_rejects_invalid_hogql(self) -> None:
        response = self.client.post(
            self._url("/preview/"),
            {
                "request_type": RequestType.EVENT_REMOVAL.value,
                "start_time": (timezone.now() - timedelta(days=2)).isoformat(),
                "end_time": (timezone.now() - timedelta(days=1)).isoformat(),
                "events": ["$pageview"],
                "hogql_predicate": "~~ not valid ~~",
            },
            format="json",
        )
        assert response.status_code == status.HTTP_400_BAD_REQUEST

    @patch("posthog.api.data_deletion_request.sync_execute")
    def test_preview_returns_count_and_sample(self, mock_sync_execute) -> None:
        mock_sync_execute.side_effect = [
            [(5, 1, timezone.now() - timedelta(days=2), timezone.now() - timedelta(days=1))],
            [
                ("uuid-1", "$pageview", timezone.now(), "did-1", "{}"),
                ("uuid-2", "$pageview", timezone.now(), "did-2", "{}"),
            ],
        ]
        response = self.client.post(
            self._url("/preview/"),
            {
                "request_type": RequestType.EVENT_REMOVAL.value,
                "start_time": (timezone.now() - timedelta(days=2)).isoformat(),
                "end_time": (timezone.now() - timedelta(days=1)).isoformat(),
                "events": ["$pageview"],
            },
            format="json",
        )
        assert response.status_code == status.HTTP_200_OK, response.json()
        body = response.json()
        assert body["count"] == 5
        assert len(body["rows"]) == 2
        assert body["rows"][0]["event"] == "$pageview"
        assert body["truncated"] is False
        assert body["limit"] == 3000

    @patch("posthog.api.data_deletion_request.sync_execute")
    def test_preview_marks_truncated_when_over_limit(self, mock_sync_execute) -> None:
        big_count = 5000
        mock_sync_execute.side_effect = [
            [(big_count, 1, timezone.now() - timedelta(days=2), timezone.now() - timedelta(days=1))],
            [("uuid", "$pageview", timezone.now(), "did", "{}") for _ in range(3001)],
        ]
        response = self.client.post(
            self._url("/preview/"),
            {
                "request_type": RequestType.EVENT_REMOVAL.value,
                "start_time": (timezone.now() - timedelta(days=2)).isoformat(),
                "end_time": (timezone.now() - timedelta(days=1)).isoformat(),
                "events": ["$pageview"],
            },
            format="json",
        )
        assert response.status_code == status.HTTP_200_OK
        body = response.json()
        assert body["truncated"] is True
        assert len(body["rows"]) == 3000
