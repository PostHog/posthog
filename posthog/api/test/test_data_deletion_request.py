from uuid import uuid4

from posthog.test.base import APIBaseTest
from unittest.mock import MagicMock, patch

from parameterized import parameterized
from rest_framework import status

from posthog.constants import AvailableFeature
from posthog.models import OrganizationMembership, Team
from posthog.models.data_deletion_request import DataDeletionRequest, ExecutionMode, RequestStatus, RequestType

from products.access_control.backend.models import AccessControl

FEATURE_FLAG = "posthog.api.data_deletion_request.self_service_data_deletion_enabled"
COMPILE_QUERY = "posthog.data_deletion.compile_event_uuid_query"


@patch(FEATURE_FLAG, return_value=True)
class TestDataDeletionRequestAPI(APIBaseTest):
    def setUp(self) -> None:
        super().setUp()
        self.organization_membership.level = OrganizationMembership.Level.ADMIN
        self.organization_membership.save(update_fields=["level"])
        self.url = f"/api/projects/{self.team.id}/data_deletion_requests"

    @patch(COMPILE_QUERY)
    def test_create_assigns_server_owned_fields_and_is_idempotent(self, compile_query, _feature_flag) -> None:
        submission_id = uuid4()
        payload = {
            "query": "SELECT uuid FROM events WHERE event = 'checkout'",
            "variables": {},
            "submission_id": str(submission_id),
        }

        first = self.client.post(f"{self.url}/", payload, format="json")
        second = self.client.post(f"{self.url}/", payload, format="json")
        conflict = self.client.post(
            f"{self.url}/",
            {**payload, "query": "SELECT uuid FROM events WHERE event = 'refund'"},
            format="json",
        )

        assert first.status_code == status.HTTP_201_CREATED, first.json()
        assert second.status_code == status.HTTP_200_OK, second.json()
        assert conflict.status_code == status.HTTP_409_CONFLICT, conflict.json()
        assert second.json()["id"] == first.json()["id"]
        request = DataDeletionRequest.objects.get(id=first.json()["id"])
        assert request.team_id == self.team.id
        assert request.created_by == self.user
        assert request.created_by_staff is self.user.is_staff
        assert request.request_type == RequestType.HOGQL_EVENT_REMOVAL
        assert request.execution_mode == ExecutionMode.DEFERRED
        assert request.status == RequestStatus.PENDING
        assert request.requires_approval is True
        assert DataDeletionRequest.objects.filter(team_id=self.team.id).count() == 1
        compile_query.assert_called_once()

    @patch(COMPILE_QUERY)
    def test_create_rejects_requests_above_the_active_limit(self, compile_query, _feature_flag) -> None:
        for _ in range(5):
            DataDeletionRequest.objects.create(
                team_id=self.team.id,
                request_type=RequestType.HOGQL_EVENT_REMOVAL,
                status=RequestStatus.PENDING,
                submission_id=uuid4(),
            )

        response = self.client.post(
            f"{self.url}/",
            {
                "query": "SELECT uuid FROM events",
                "variables": {},
                "submission_id": str(uuid4()),
            },
            format="json",
        )

        assert response.status_code == status.HTTP_409_CONFLICT, response.json()
        assert DataDeletionRequest.objects.filter(team_id=self.team.id).count() == 5
        compile_query.assert_not_called()

    @parameterized.expand(
        [
            ("status", RequestStatus.COMPLETED),
            ("request_type", RequestType.PROPERTY_REMOVAL),
            ("team_id", 123456),
            ("execution_mode", ExecutionMode.IMMEDIATE),
        ]
    )
    @patch(COMPILE_QUERY)
    def test_create_rejects_server_owned_fields(
        self,
        field: str,
        value: object,
        compile_query: MagicMock,
        _feature_flag: MagicMock,
    ) -> None:
        response = self.client.post(
            f"{self.url}/",
            {
                "query": "SELECT uuid FROM events",
                "variables": {},
                "submission_id": str(uuid4()),
                field: value,
            },
            format="json",
        )

        assert response.status_code == status.HTTP_400_BAD_REQUEST
        assert response.json()["attr"] == field
        assert response.json()["detail"] == "This field is not accepted."
        assert DataDeletionRequest.objects.filter(team_id=self.team.id).count() == 0
        compile_query.assert_not_called()

    def test_list_and_detail_do_not_expose_other_projects(self, _feature_flag) -> None:
        other_team = Team.objects.create(organization=self.organization)
        visible = DataDeletionRequest.objects.create(
            team_id=self.team.id,
            request_type=RequestType.HOGQL_EVENT_REMOVAL,
            execution_mode=ExecutionMode.DEFERRED,
            hogql_query="SELECT uuid FROM events",
        )
        hidden = DataDeletionRequest.objects.create(
            team_id=other_team.id,
            request_type=RequestType.HOGQL_EVENT_REMOVAL,
            execution_mode=ExecutionMode.DEFERRED,
            hogql_query="SELECT uuid FROM events",
        )

        listing = self.client.get(f"{self.url}/")
        hidden_detail = self.client.get(f"{self.url}/{hidden.id}/")

        assert listing.status_code == status.HTTP_200_OK
        assert [item["id"] for item in listing.json()["results"]] == [str(visible.id)]
        assert hidden_detail.status_code == status.HTTP_404_NOT_FOUND

    def test_preview_rejects_non_object_variables(self, _feature_flag) -> None:
        response = self.client.post(
            f"{self.url}/preview/",
            {"query": "SELECT uuid FROM events", "variables": []},
            format="json",
        )

        assert response.status_code == status.HTTP_400_BAD_REQUEST
        assert response.json()["attr"] == "variables"
        assert response.json()["detail"] == "Query variables must be a JSON object."

    @patch("posthog.api.data_deletion_request.preview_event_deletion", return_value=123)
    def test_preview_returns_the_server_count(self, preview, _feature_flag) -> None:
        response = self.client.post(
            f"{self.url}/preview/",
            {"query": "SELECT uuid FROM events", "variables": {}},
            format="json",
        )

        assert response.status_code == status.HTTP_200_OK, response.json()
        assert response.json() == {"count": 123}
        preview.assert_called_once()

    @patch("posthog.rate_limit.is_rate_limit_enabled", return_value=True)
    @patch("posthog.api.data_deletion_request.preview_event_deletion", return_value=1)
    def test_preview_throttles_session_requests(self, _preview, _rate_limit, _feature_flag) -> None:
        responses = [
            self.client.post(
                f"{self.url}/preview/",
                {"query": "SELECT uuid FROM events", "variables": {}},
                format="json",
            )
            for _ in range(6)
        ]

        assert [response.status_code for response in responses] == [
            status.HTTP_200_OK,
            status.HTTP_200_OK,
            status.HTTP_200_OK,
            status.HTTP_200_OK,
            status.HTTP_200_OK,
            status.HTTP_429_TOO_MANY_REQUESTS,
        ]


class TestDataDeletionRequestAPIAccess(APIBaseTest):
    def test_feature_flag_gates_the_whole_surface(self) -> None:
        self.organization_membership.level = OrganizationMembership.Level.ADMIN
        self.organization_membership.save(update_fields=["level"])
        url = f"/api/projects/{self.team.id}/data_deletion_requests"

        with patch(FEATURE_FLAG, return_value=False):
            assert self.client.get(f"{url}/").status_code == status.HTTP_403_FORBIDDEN
            assert self.client.post(f"{url}/preview/", {}).status_code == status.HTTP_403_FORBIDDEN

    def test_organization_member_has_no_deletion_access_by_default(self) -> None:
        url = f"/api/projects/{self.team.id}/data_deletion_requests/"

        with patch(FEATURE_FLAG, return_value=True):
            response = self.client.get(url)

        assert response.status_code == status.HTTP_403_FORBIDDEN

    def test_organization_member_with_explicit_access_can_preview(self) -> None:
        url = f"/api/projects/{self.team.id}/data_deletion_requests/preview/"
        self.organization.available_product_features = [
            {"key": AvailableFeature.ACCESS_CONTROL, "name": AvailableFeature.ACCESS_CONTROL}
        ]
        self.organization.save(update_fields=["available_product_features"])
        AccessControl.objects.create(
            team=self.team,
            resource="data_deletion",
            access_level="editor",
            organization_member=self.organization_membership,
        )

        with (
            patch(FEATURE_FLAG, return_value=True),
            patch("posthog.api.data_deletion_request.preview_event_deletion", return_value=1),
        ):
            response = self.client.post(url, {"query": "SELECT uuid FROM events"}, format="json")

        assert response.status_code == status.HTTP_200_OK
