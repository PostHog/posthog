from posthog.test.base import APIBaseTest
from unittest.mock import MagicMock, patch

from parameterized import parameterized
from rest_framework import status
from rest_framework.response import Response

from posthog.ducklake.models import DuckgresServer
from posthog.models.organization import OrganizationMembership

ADAPTER = "products.data_warehouse.backend.presentation.views.managed_warehouse_users"


def _duckgres_user(username: str, disabled: bool = False) -> dict:
    # Shape of a duckgres OrgUser as serialized by the control plane (password is json:"-").
    return {
        "org_id": "ignored",
        "username": username,
        "passthrough": False,
        "disabled": disabled,
        "max_vcpus": 4,
        "created_at": "2026-07-01T00:00:00Z",
        "updated_at": "2026-07-02T00:00:00Z",
    }


class TestManagedWarehouseUsersAPI(APIBaseTest):
    def _url(self, suffix: str = "") -> str:
        return f"/api/environments/{self.team.pk}/data_warehouse/users/{suffix}"

    def _make_admin(self) -> None:
        self.organization_membership.level = OrganizationMembership.Level.ADMIN
        self.organization_membership.save()

    def _create_server(self, username: str = "root") -> DuckgresServer:
        return DuckgresServer.objects.create(
            organization=self.organization,
            host="my-warehouse.dw.us.postwh.com",
            port=5432,
            database="ducklake",
            username=username,
            password="rootpw",
        )

    @patch(f"{ADAPTER}._request")
    def test_list_users_presents_org_scoped_users_without_internal_knobs(self, mock_request: MagicMock) -> None:
        mock_request.return_value = Response(
            {"name": str(self.team.organization_id), "users": [_duckgres_user("zeta"), _duckgres_user("alpha", True)]},
            status=status.HTTP_200_OK,
        )

        response = self.client.get(self._url())

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        # Org id comes from the team context, via the org-scoped endpoint (empty path = /orgs/{org}).
        mock_request.assert_called_once_with("GET", self.team.organization_id, "")
        self.assertEqual(
            response.json(),
            [
                {
                    "username": "alpha",
                    "disabled": True,
                    "created_at": "2026-07-01T00:00:00Z",
                    "updated_at": "2026-07-02T00:00:00Z",
                },
                {
                    "username": "zeta",
                    "disabled": False,
                    "created_at": "2026-07-01T00:00:00Z",
                    "updated_at": "2026-07-02T00:00:00Z",
                },
            ],
        )

    @patch(f"{ADAPTER}._request")
    def test_create_user_returns_generated_password_and_connection(self, mock_request: MagicMock) -> None:
        self._make_admin()
        self._create_server()
        mock_request.return_value = Response(_duckgres_user("analyst"), status=status.HTTP_201_CREATED)

        response = self.client.post(self._url(), {"username": "analyst"})

        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        body = response.json()
        # The org id and the generated password sent to duckgres come from the server side.
        call_kwargs = mock_request.call_args.kwargs
        self.assertEqual(mock_request.call_args.args, ("POST", self.team.organization_id, "users"))
        self.assertEqual(call_kwargs["json_body"]["org_id"], str(self.team.organization_id))
        self.assertEqual(call_kwargs["json_body"]["username"], "analyst")
        self.assertEqual(body["password"], call_kwargs["json_body"]["password"])
        self.assertGreaterEqual(len(body["password"]), 32)
        self.assertEqual(
            body["connection"],
            {"host": "my-warehouse.dw.us.postwh.com", "port": 5432, "database": "ducklake", "username": "analyst"},
        )

    @parameterized.expand(
        [
            ("create", "post", "", {"username": "analyst"}),
            ("delete", "delete", "bob/", None),
            ("reset_password", "post", "bob/reset-password/", None),
            ("disable", "post", "bob/disable/", None),
            ("enable", "post", "bob/enable/", None),
        ]
    )
    @patch(f"{ADAPTER}._request")
    def test_mutations_require_org_admin(
        self, _name: str, method: str, suffix: str, data: dict | None, mock_request: MagicMock
    ) -> None:
        response = getattr(self.client, method)(self._url(suffix), data)

        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)
        self.assertIn("organization admins", response.json()["error"])
        mock_request.assert_not_called()

    @patch(f"{ADAPTER}._request")
    def test_non_admin_can_list_users(self, mock_request: MagicMock) -> None:
        mock_request.return_value = Response({"name": "org", "users": []}, status=status.HTTP_200_OK)

        response = self.client.get(self._url())

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.json(), [])

    @parameterized.expand(
        [
            ("delete_root", "delete", "root/"),
            ("disable_root", "post", "root/disable/"),
            ("reset_root", "post", "root/reset-password/"),
            ("delete_server_username", "delete", "warehouse_admin/"),
            ("disable_server_username", "post", "warehouse_admin/disable/"),
            ("reset_server_username", "post", "warehouse_admin/reset-password/"),
        ]
    )
    @patch(f"{ADAPTER}._request")
    def test_root_user_is_protected_from_mutations(
        self, _name: str, method: str, suffix: str, mock_request: MagicMock
    ) -> None:
        self._make_admin()
        # The org's root user may have a custom name — protection must cover it too.
        self._create_server(username="warehouse_admin")

        response = getattr(self.client, method)(self._url(suffix))

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("warehouse settings", response.json()["error"])
        mock_request.assert_not_called()

    @patch(f"{ADAPTER}._request")
    def test_create_rejects_root_username_collision(self, mock_request: MagicMock) -> None:
        self._make_admin()
        self._create_server(username="warehouse_admin")

        response = self.client.post(self._url(), {"username": "warehouse_admin"})

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("reserved", response.json()["error"])
        mock_request.assert_not_called()

    @parameterized.expand(
        [
            ("missing", None),
            ("empty", ""),
            ("too_short", "ab"),
            ("starts_with_digit", "1analyst"),
            ("starts_with_underscore", "_analyst"),
            ("uppercase", "Analyst"),
            ("hyphen", "my-user"),
            ("too_long", "a" * 64),
            ("reserved_root", "root"),
            ("reserved_postgres", "postgres"),
            ("reserved_admin", "admin"),
        ]
    )
    @patch(f"{ADAPTER}._request")
    def test_create_rejects_invalid_usernames(self, _name: str, username: str | None, mock_request: MagicMock) -> None:
        self._make_admin()

        response = self.client.post(self._url(), {"username": username} if username is not None else {})

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        mock_request.assert_not_called()

    @patch(f"{ADAPTER}._request")
    def test_create_passes_duckgres_error_through_without_leaking_password(self, mock_request: MagicMock) -> None:
        self._make_admin()
        mock_request.return_value = Response({"error": "boom"}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

        response = self.client.post(self._url(), {"username": "analyst"})

        self.assertEqual(response.status_code, status.HTTP_500_INTERNAL_SERVER_ERROR)
        self.assertEqual(response.json(), {"error": "boom"})

    @patch(f"{ADAPTER}._request")
    def test_list_passes_duckgres_error_through(self, mock_request: MagicMock) -> None:
        mock_request.return_value = Response({"error": "unreachable"}, status=status.HTTP_502_BAD_GATEWAY)

        response = self.client.get(self._url())

        self.assertEqual(response.status_code, status.HTTP_502_BAD_GATEWAY)
        self.assertEqual(response.json(), {"error": "unreachable"})

    @patch(f"{ADAPTER}._request")
    def test_delete_targets_org_scoped_user_path(self, mock_request: MagicMock) -> None:
        self._make_admin()
        mock_request.return_value = Response({"deleted": "bob"}, status=status.HTTP_200_OK)

        response = self.client.delete(self._url("bob/"))

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        mock_request.assert_called_once_with("DELETE", self.team.organization_id, "/users/bob")

    @patch(f"{ADAPTER}._request")
    def test_reset_password_returns_new_password_once(self, mock_request: MagicMock) -> None:
        self._make_admin()
        mock_request.return_value = Response(_duckgres_user("bob"), status=status.HTTP_200_OK)

        response = self.client.post(self._url("bob/reset-password/"))

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        body = response.json()
        call_kwargs = mock_request.call_args.kwargs
        self.assertEqual(mock_request.call_args.args, ("PUT", self.team.organization_id, "/users/bob"))
        self.assertEqual(call_kwargs["json_body"], {"password": body["password"]})
        self.assertEqual(body["username"], "bob")

    @parameterized.expand(
        [
            ("disable", "disable"),
            ("enable", "enable"),
        ]
    )
    @patch(f"{ADAPTER}._request")
    def test_disable_and_enable_hit_kill_switch_endpoints(self, _name: str, verb: str, mock_request: MagicMock) -> None:
        self._make_admin()
        mock_request.return_value = Response({"disabled": verb == "disable"}, status=status.HTTP_200_OK)

        response = self.client.post(self._url(f"bob/{verb}/"))

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        mock_request.assert_called_once_with("POST", self.team.organization_id, f"/users/bob/{verb}")
