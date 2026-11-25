from datetime import UTC, datetime
from typing import Any

import time_machine
from posthog.test.base import APIBaseTest
from unittest.mock import patch

from django.test import override_settings

import requests
from parameterized import parameterized
from rest_framework import status
from structlog.testing import capture_logs

from posthog.models.organization import Organization, OrganizationMembership
from posthog.models.personal_api_key import PersonalAPIKey
from posthog.models.team import Team
from posthog.models.utils import generate_random_token_personal, hash_key_value
from posthog.test.project_access import restrict_project

from products.managed_warehouse.backend.facade.console import get_console_settings


class TranslatedResponse:
    """Stands in for hogtower's TranslatedResponse, which is internal to the product."""

    def __init__(self, status_code: int, body: Any, from_json: bool = True) -> None:
        self.status_code = status_code
        self.body = body
        self.from_json = from_json

    def json(self) -> Any:
        return self.body

    @property
    def ok(self) -> bool:
        return 200 <= self.status_code < 300


_SEND = "products.managed_warehouse.backend.presentation.hogtower._send"
_ENABLED = "products.managed_warehouse.backend.facade.console._is_console_enabled"
QUERY_ID = "20261120_101500_00001_abcde"

STORAGE_BODY = {
    "tables": [
        {
            "schema": "s",
            "table": "t",
            "data_bytes": 10,
            "delete_bytes": 1,
            "file_count": 2,
            "row_count": 3,
            "last_modified_at": None,
        }
    ],
    "total_bytes": 10,
    "pending_deletion_files": 0,
    "read_at": "2026-11-20T10:00:00Z",
}
USAGE_BODY = {"from": "a", "to": "b", "group_by": "day", "compute": [], "storage": []}
HISTORY_ROW: dict[str, Any] = {
    "id": 9,
    "query_id": QUERY_ID,
    "principal": "dbt_user",
    "team_id": None,
    "source": "dbt-trino",
    "state": "FAILED",
    "error_code": "X",
    "error_type": "USER_ERROR",
    "created_at": None,
    "completed_at": "2026-11-20T10:15:01Z",
    "elapsed_ms": 5,
    "queued_ms": None,
    "logical_bytes_scanned": 2 * 1024**4,
    "billable": True,
    "cpu_seconds": 1.5,
    "query": "select 1",
}
HISTORY_BODY: dict[str, Any] = {
    "queries": [HISTORY_ROW, {**HISTORY_ROW, "id": 8, "billable": False}],
    "next_cursor": "c-4",
}


def _user(username: str, mode: str, team_id: int | None = None, disabled: bool = False) -> dict[str, Any]:
    return {
        "org_id": "o",
        "username": username,
        "access_mode": mode,
        "team_id": team_id,
        "disabled": disabled,
        "created_at": "2026-11-01T00:00:00Z",
        "updated_at": "2026-11-02T00:00:00Z",
    }


SECRET = "generated-password-never-listed"


@override_settings(HOGTOWER_API_URL="http://hogtower.invalid")
class TestManagedWarehouseConsoleAPI(APIBaseTest):
    def setUp(self) -> None:
        super().setUp()
        patcher = patch(_ENABLED, return_value=True)
        patcher.start()
        self.addCleanup(patcher.stop)

    def _url(self, path: str) -> str:
        return f"/api/projects/{self.team.id}/managed_warehouse_console/{path}"

    def _set_level(self, level: OrganizationMembership.Level) -> None:
        self.organization_membership.level = level
        self.organization_membership.save()

    def _send(self, status_code: int, body: Any):
        return patch(_SEND, return_value=TranslatedResponse(status_code, body))

    @parameterized.expand(
        [
            ("usage", "get", "usage/"),
            ("queries", "get", "queries/"),
            ("storage", "get", "storage/"),
            ("settings", "get", "settings/"),
            ("settings update", "patch", "settings/"),
            ("cancel", "post", f"queries/{QUERY_ID}/cancel/"),
        ]
    )
    def test_not_found_when_warehouse_not_enabled(self, _name: str, method: str, path: str) -> None:
        self._set_level(OrganizationMembership.Level.ADMIN)
        with patch(_ENABLED, return_value=False), patch(_SEND) as send:
            response = getattr(self.client, method)(self._url(path), {}, format="json")

        assert response.status_code == status.HTTP_404_NOT_FOUND
        assert "not enabled" in response.json()["error"]
        send.assert_not_called()

    def test_usage_returns_decimal_strings_and_calls_hogtower_twice(self) -> None:
        with patch(_SEND, return_value=TranslatedResponse(200, USAGE_BODY)) as send:
            response = self.client.get(self._url("usage/?period=last_month&group_by=principal"))

        assert response.status_code == status.HTTP_200_OK
        data = response.json()
        assert data["compute"]["estimated_cost_usd"] == "0.000000"
        assert data["forecast_total_usd"] is None
        assert sorted(c.kwargs["params"]["group_by"] for c in send.call_args_list) == ["day", "principal"]

    def test_usage_current_month_has_forecast_and_days_up_to_today(self) -> None:
        with time_machine.travel(datetime(2026, 3, 10, 12, tzinfo=UTC), tick=False):
            with patch(_SEND, return_value=TranslatedResponse(200, USAGE_BODY)):
                data = self.client.get(self._url("usage/?period=current_month")).json()

        assert data["period_start"] == "2026-03-01" and data["period_end"] == "2026-04-01"
        assert len(data["daily"]) == 10
        assert data["forecast_total_usd"] == "0.000000"

    def test_usage_rejects_unknown_group_by(self) -> None:
        response = self.client.get(self._url("usage/?group_by=nope"))
        assert response.status_code == status.HTTP_400_BAD_REQUEST

    def test_queries_adds_estimated_cost_and_forwards_filters(self) -> None:
        with self._send(200, HISTORY_BODY) as send:
            response = self.client.get(self._url("queries/?state=FAILED&team_id=3&limit=5&cursor=abc"))

        assert response.status_code == status.HTTP_200_OK
        row = response.json()["queries"][0]
        assert row["estimated_cost_usd"] == "5.000000"
        assert row["principal_label"] == "dbt_user"
        assert row["billable"] is True and row["billable_bytes"] == 2 * 1024**4
        free = response.json()["queries"][1]
        assert free["billable"] is False and free["billable_bytes"] == 0 and free["estimated_cost_usd"] == "0.000000"
        assert response.json()["next_cursor"] == "c-4"
        assert send.call_args.kwargs["params"] == {"state": "FAILED", "team_id": 3, "limit": 5, "cursor": "abc"}

    @parameterized.expand(
        [
            ("too wide", "from=2026-10-01T00:00:00Z&to=2026-11-05T00:00:00Z", status.HTTP_400_BAD_REQUEST),
            ("31 days", "from=2026-10-01T00:00:00Z&to=2026-11-01T00:00:00Z", status.HTTP_200_OK),
        ]
    )
    def test_queries_window_is_capped_at_31_days(self, _name: str, query: str, expected: int) -> None:
        with self._send(200, {"queries": [], "next_cursor": None}) as send:
            response = self.client.get(self._url(f"queries/?{query}"))
        assert response.status_code == expected
        assert send.called == (expected == status.HTTP_200_OK)

    @parameterized.expand(
        [
            (f"{read} {who}", path, who, expected)
            for read, path in (
                ("usage", "usage/"),
                ("queries", "queries/"),
                ("storage", "storage/"),
                ("settings", "settings/"),
            )
            for who, expected in (
                ("admin", status.HTTP_200_OK),
                ("member with every project", status.HTTP_200_OK),
                ("member without one project", status.HTTP_403_FORBIDDEN),
            )
        ]
    )
    def test_warehouse_wide_reads_need_admin_or_access_to_every_project(
        self, _name: str, path: str, who: str, expected: int
    ) -> None:
        self._set_level(OrganizationMembership.Level.ADMIN if who == "admin" else OrganizationMembership.Level.MEMBER)
        if who != "member with every project":
            # An admin keeps access to a restricted project, so the admin case still passes.
            restrict_project(
                Team.objects.create(organization=self.organization, name="Private"),
                plain_members=[] if who == "admin" else [self.organization_membership],
            )

        def send(method: str, request_path: str, **kwargs: Any) -> TranslatedResponse:
            for suffix, body in (("/usage", USAGE_BODY), ("/queries", HISTORY_BODY), ("/tables", STORAGE_BODY)):
                if request_path.endswith(suffix):
                    return TranslatedResponse(200, body)
            return TranslatedResponse(200, {"status": "idle"})

        with patch(_SEND, side_effect=send) as upstream:
            response = self.client.get(self._url(path))

        assert response.status_code == expected
        if expected == status.HTTP_403_FORBIDDEN:
            assert response.json() == {
                "error": "You need access to every project in this organization to see warehouse-wide data."
            }
            upstream.assert_not_called()

    def test_upstream_unavailable_is_503(self) -> None:
        with self._send(503, {"error": "x"}):
            assert self.client.get(self._url("storage/")).status_code == status.HTTP_503_SERVICE_UNAVAILABLE

    def test_upstream_timeout_is_502(self) -> None:
        with patch(_SEND, side_effect=requests.Timeout("slow")):
            response = self.client.get(self._url("storage/"))
        assert response.status_code == status.HTTP_502_BAD_GATEWAY

    def test_malformed_upstream_body_is_502(self) -> None:
        with self._send(200, {"tables": [{"schema": "only-a-schema"}]}):
            assert self.client.get(self._url("storage/")).status_code == status.HTTP_502_BAD_GATEWAY

    @parameterized.expand(
        [
            ("server error", 500, {"error": "internal stack trace"}, True),
            ("unavailable", 503, {"error": "internal stack trace"}, True),
            ("non-json rejection", 400, {"error": "internal stack trace"}, False),
            ("multi-line rejection", 400, {"error": "first line\ninternal stack trace"}, True),
            ("long rejection", 400, {"error": "internal stack trace " * 20}, True),
        ]
    )
    def test_upstream_text_is_not_forwarded(self, _name: str, upstream: int, body: dict, from_json: bool) -> None:
        with patch(_SEND, return_value=TranslatedResponse(upstream, body, from_json=from_json)):
            response = self.client.get(self._url("storage/"))
        assert "internal stack trace" not in response.content.decode()

    @override_settings(HOGTOWER_API_URL="")
    def test_unconfigured_control_plane_is_501(self) -> None:
        assert self.client.get(self._url("storage/")).status_code == status.HTTP_501_NOT_IMPLEMENTED

    def test_storage_includes_maintenance_or_null(self) -> None:
        def send(method: str, path: str, **kwargs: Any) -> TranslatedResponse:
            if path.endswith("/maintenance"):
                return TranslatedResponse(200, {"status": "idle"})
            return TranslatedResponse(200, STORAGE_BODY)

        with patch(_SEND, side_effect=send):
            data = self.client.get(self._url("storage/")).json()
        assert data["maintenance"] == {"status": "idle"}
        assert data["tables"][0]["table"] == "t"

        with patch(
            _SEND,
            side_effect=lambda m, p, **k: TranslatedResponse(*((500, {}) if "maint" in p else (200, STORAGE_BODY))),
        ):
            assert self.client.get(self._url("storage/")).json()["maintenance"] is None

    @parameterized.expand(
        [
            ("member", OrganizationMembership.Level.MEMBER, status.HTTP_403_FORBIDDEN),
            ("admin", OrganizationMembership.Level.ADMIN, status.HTTP_200_OK),
        ]
    )
    def test_settings_patch_needs_admin(self, _name: str, level: OrganizationMembership.Level, expected: int) -> None:
        self._set_level(level)
        response = self.client.patch(
            self._url("settings/"),
            {"max_scan_bytes_per_query": 2 * 1024**3, "monthly_budget_usd": "50.5"},
            format="json",
        )
        assert response.status_code == expected
        if expected == status.HTTP_200_OK:
            assert response.json() == {"max_scan_bytes_per_query": 2 * 1024**3, "monthly_budget_usd": "50.50"}
        else:
            assert get_console_settings(str(self.organization.id)).monthly_budget_usd is None

    def test_settings_patch_keeps_omitted_fields_and_allows_null(self) -> None:
        self._set_level(OrganizationMembership.Level.ADMIN)
        self.client.patch(self._url("settings/"), {"monthly_budget_usd": "10"}, format="json")
        self.client.patch(self._url("settings/"), {"max_scan_bytes_per_query": 1024**3}, format="json")
        assert self.client.get(self._url("settings/")).json() == {
            "max_scan_bytes_per_query": 1024**3,
            "monthly_budget_usd": "10.00",
        }
        cleared = self.client.patch(self._url("settings/"), {"max_scan_bytes_per_query": None}, format="json")
        assert cleared.json()["max_scan_bytes_per_query"] is None

    @parameterized.expand(
        [
            ("cap below 1 GiB", {"max_scan_bytes_per_query": 1024**3 - 1}),
            ("negative budget", {"monthly_budget_usd": "-1"}),
            ("zero budget", {"monthly_budget_usd": "0"}),
            ("cap beyond bigint", {"max_scan_bytes_per_query": 2**63}),
        ]
    )
    def test_settings_validation(self, _name: str, body: dict) -> None:
        self._set_level(OrganizationMembership.Level.ADMIN)
        assert self.client.patch(self._url("settings/"), body, format="json").status_code == 400

    def test_cancel_as_admin(self) -> None:
        self._set_level(OrganizationMembership.Level.ADMIN)
        with self._send(202, {"status": "cancel_requested"}) as send:
            response = self.client.post(self._url(f"queries/{QUERY_ID}/cancel/"), {}, format="json")

        assert response.status_code == status.HTTP_202_ACCEPTED
        assert response.json() == {"status": "cancel_requested"}
        assert send.call_args.args[0] == "DELETE" and send.call_args.args[1].endswith(f"/trino/queries/{QUERY_ID}")
        assert send.call_args.kwargs["params"] is None

    def test_cancel_not_found_or_finished(self) -> None:
        self._set_level(OrganizationMembership.Level.ADMIN)
        with self._send(404, {}):
            response = self.client.post(self._url(f"queries/{QUERY_ID}/cancel/"), {}, format="json")
        assert response.status_code == status.HTTP_404_NOT_FOUND

    def test_cancel_rejects_malformed_query_id(self) -> None:
        self._set_level(OrganizationMembership.Level.ADMIN)
        response = self.client.post(self._url("queries/not-a-query/cancel/"), {}, format="json")
        assert response.status_code == status.HTTP_400_BAD_REQUEST

    def test_member_may_cancel_only_with_own_sql_editor_principal(self) -> None:
        self._set_level(OrganizationMembership.Level.MEMBER)
        own = f"posthog:sql-editor:team:{self.team.pk}:user:{self.user.pk}"
        others = [
            f"posthog:sql-editor:team:{self.team.pk}:user:{self.user.pk + 1}",
            f"posthog:sql-editor:team:999999:user:{self.user.pk}",
            "dbt_user",
        ]
        with self._send(202, {"status": "cancel_requested"}) as send:
            for principal in others:
                response = self.client.post(
                    self._url(f"queries/{QUERY_ID}/cancel/"), {"principal": principal}, format="json"
                )
                assert response.status_code == status.HTTP_403_FORBIDDEN
            send.assert_not_called()
            response = self.client.post(self._url(f"queries/{QUERY_ID}/cancel/"), {"principal": own}, format="json")
        assert response.status_code == status.HTTP_202_ACCEPTED
        assert send.call_args.kwargs["params"] == {"principal": own}

    def _login_routes(self, users: list[dict], **extra: Any):
        def send(method: str, path: str, **kwargs: Any) -> TranslatedResponse:
            if method == "GET" and path.endswith("/users"):
                return TranslatedResponse(200, {"users": users})
            if method == "GET" and path.endswith("/usage"):
                row = {"key": "reader_team", "queries": 4, "billable_bytes": 7}
                return TranslatedResponse(200, {"compute": [row], "storage": []})
            return extra[method]

        return patch(_SEND, side_effect=send)

    def test_logins_list_merges_activity_and_scope_labels(self) -> None:
        self._set_level(OrganizationMembership.Level.ADMIN)
        users = [
            _user("reader_team", "project_reader", self.team.pk),
            _user("root", "unrestricted"),
            _user("writer_team", "project_user", self.team.pk, disabled=True),
        ]
        with self._login_routes(users):
            response = self.client.get(self._url("logins/"))

        logins = {login["username"]: login for login in response.json()["logins"]}
        assert logins["reader_team"]["scope_label"] == f"Read only · {self.team.name}"
        assert (logins["reader_team"]["queries_30d"], logins["reader_team"]["billable_bytes_30d"]) == (4, 7)
        assert logins["writer_team"]["scope_label"] == f"Read and write · {self.team.name}"
        assert logins["writer_team"]["disabled"] is True and logins["writer_team"]["queries_30d"] == 0
        assert (logins["root"]["kind"], logins["root"]["scope_label"]) == ("root", "Root")
        assert "password" not in response.content.decode()

    def test_logins_list_survives_missing_activity(self) -> None:
        self._set_level(OrganizationMembership.Level.ADMIN)

        def send(method: str, path: str, **kwargs: Any) -> TranslatedResponse:
            if path.endswith("/usage"):
                return TranslatedResponse(500, {})
            return TranslatedResponse(200, {"users": [_user("reader_team", "project_reader", self.team.pk)]})

        with patch(_SEND, side_effect=send):
            logins = self.client.get(self._url("logins/")).json()["logins"]
        assert logins[0]["queries_30d"] == 0

    def test_create_login_returns_password_once(self) -> None:
        self._set_level(OrganizationMembership.Level.ADMIN)
        created = {"user": _user("reader_team", "project_reader", self.team.pk), "password": SECRET}
        with self._login_routes([], PUT=TranslatedResponse(200, created)) as send:
            response = self.client.post(
                self._url("logins/"), {"team_id": self.team.pk, "mode": "reader"}, format="json"
            )
        assert response.status_code == status.HTTP_200_OK
        assert response.json()["password"] == SECRET
        put = next(c for c in send.call_args_list if c.args[0] == "PUT")
        assert put.args[1].endswith(f"/teams/{self.team.pk}/logins/reader")
        with self._login_routes([_user("reader_team", "project_reader", self.team.pk)]):
            assert SECRET not in self.client.get(self._url("logins/")).content.decode()

    def test_create_login_rejects_team_of_another_organization(self) -> None:
        self._set_level(OrganizationMembership.Level.ADMIN)
        other_team = Team.objects.create(organization=Organization.objects.create(name="Other"), name="Elsewhere")
        with patch(_SEND) as send:
            response = self.client.post(self._url("logins/"), {"team_id": other_team.pk, "mode": "user"}, format="json")
        assert response.status_code == status.HTTP_400_BAD_REQUEST
        send.assert_not_called()

    def test_create_login_rejects_unknown_mode(self) -> None:
        self._set_level(OrganizationMembership.Level.ADMIN)
        response = self.client.post(self._url("logins/"), {"team_id": self.team.pk, "mode": "root"}, format="json")
        assert response.status_code == status.HTTP_400_BAD_REQUEST

    def test_create_login_surfaces_control_plane_rejection(self) -> None:
        self._set_level(OrganizationMembership.Level.ADMIN)
        with patch(_SEND, return_value=TranslatedResponse(409, {"error": "project is not set up in the warehouse"})):
            response = self.client.post(self._url("logins/"), {"team_id": self.team.pk, "mode": "user"}, format="json")
        assert response.status_code == status.HTTP_400_BAD_REQUEST
        assert response.json()["error"] == "project is not set up in the warehouse"

    def test_rotate_disable_and_delete(self) -> None:
        self._set_level(OrganizationMembership.Level.ADMIN)
        user = _user("reader_team", "project_reader", self.team.pk)
        routes = {"PATCH": TranslatedResponse(200, {"user": user, "password": SECRET})}
        with self._login_routes([user], **routes) as send, capture_logs() as logs:
            rotated = self.client.post(self._url("logins/reader_team/rotate/"), {}, format="json")
        assert rotated.json()["password"] == SECRET
        assert rotated["Cache-Control"] == "no-store"
        assert send.call_args.kwargs["json_body"] == {"rotate_password": True}
        assert SECRET not in str(logs)

        routes = {"PATCH": TranslatedResponse(200, {"user": {**user, "disabled": True}})}
        with self._login_routes([user], **routes) as send:
            disabled = self.client.patch(self._url("logins/reader_team/"), {"disabled": True}, format="json")
        assert disabled.json()["disabled"] is True and "password" not in disabled.json()
        assert send.call_args.kwargs["json_body"] == {"disabled": True}

        with self._login_routes([user], DELETE=TranslatedResponse(200, {"deleted": "reader_team"})) as send:
            deleted = self.client.delete(self._url("logins/reader_team/"))
        assert deleted.status_code == status.HTTP_204_NO_CONTENT
        assert send.call_args.args[0] == "DELETE"

    @parameterized.expand(
        [
            (f"{login} {action}", login, method, path, body)
            for login in ("root", "ROOT", "svc_admin")
            for action, method, path, body in (
                ("rotate", "post", "rotate/", {}),
                ("disable", "patch", "", {"disabled": True}),
                ("delete", "delete", "", None),
            )
        ]
    )
    def test_only_project_logins_can_be_changed(
        self, _name: str, login: str, method: str, path: str, body: dict | None
    ) -> None:
        self._set_level(OrganizationMembership.Level.ADMIN)
        with self._login_routes([_user(login, "unrestricted")]) as send:
            response = getattr(self.client, method)(self._url(f"logins/{login}/{path}"), body, format="json")
        assert response.status_code == status.HTTP_400_BAD_REQUEST
        assert "project logins" in response.json()["error"]
        assert [c.args[0] for c in send.call_args_list] == ["GET"]

    def test_missing_login_is_404_without_a_change(self) -> None:
        self._set_level(OrganizationMembership.Level.ADMIN)
        with self._login_routes([_user("reader_team", "project_reader", self.team.pk)]) as send:
            assert self.client.delete(self._url("logins/ghost/")).status_code == status.HTTP_404_NOT_FOUND
        assert [c.args[0] for c in send.call_args_list] == ["GET"]

    def test_create_login_password_never_reaches_logs(self) -> None:
        self._set_level(OrganizationMembership.Level.ADMIN)
        created = {"user": _user("reader_team", "project_reader", self.team.pk), "password": SECRET}
        with self._login_routes([], PUT=TranslatedResponse(200, created)), capture_logs() as logs:
            self.client.post(self._url("logins/"), {"team_id": self.team.pk, "mode": "reader"}, format="json")
        assert logs and SECRET not in str(logs)

    @parameterized.expand(
        [
            ("list", "get", "logins/", None),
            ("create", "post", "logins/", {"team_id": 1, "mode": "reader"}),
            ("rotate", "post", "logins/reader_team/rotate/", {}),
            ("disable", "patch", "logins/reader_team/", {"disabled": True}),
            ("delete", "delete", "logins/reader_team/", None),
        ]
    )
    def test_logins_need_organization_admin(self, _name: str, method: str, path: str, body: dict | None) -> None:
        self._set_level(OrganizationMembership.Level.MEMBER)
        with patch(_SEND) as send:
            response = getattr(self.client, method)(self._url(path), body, format="json")
        assert response.status_code == status.HTTP_403_FORBIDDEN
        send.assert_not_called()


@override_settings(HOGTOWER_API_URL="http://hogtower.invalid")
class TestManagedWarehouseConsoleTokenAuth(APIBaseTest):
    CONFIG_AUTO_LOGIN = False

    def setUp(self) -> None:
        super().setUp()
        self.organization_membership.level = OrganizationMembership.Level.ADMIN
        self.organization_membership.save()
        patcher = patch(_ENABLED, return_value=True)
        patcher.start()
        self.addCleanup(patcher.stop)

    def _call(self, method: str, path: str, key: str, body: dict | None = None):
        return getattr(self.client, method)(
            f"/api/projects/{self.team.id}/managed_warehouse_console/{path}",
            body or {},
            content_type="application/json",
            headers={"authorization": f"Bearer {key}"},
        )

    @parameterized.expand(
        [
            ("create", "post", "logins/", {"team_id": 1, "mode": "reader"}),
            ("rotate", "post", "logins/reader_team/rotate/", {}),
            ("disable", "patch", "logins/reader_team/", {"disabled": True}),
            ("delete", "delete", "logins/reader_team/", None),
        ]
    )
    def test_api_key_cannot_change_logins(self, _name: str, method: str, path: str, body: dict | None) -> None:
        key = self.create_personal_api_key_with_scopes(["warehouse_view:write"])
        with patch(_SEND) as send:
            response = self._call(method, path, key, body)
        assert response.status_code == status.HTTP_403_FORBIDDEN
        send.assert_not_called()

    @parameterized.expand(
        [
            ("settings update", "patch", "settings/", {"monthly_budget_usd": "5"}),
            ("cancel", "post", f"queries/{QUERY_ID}/cancel/", {}),
        ]
    )
    def test_read_key_cannot_write(self, _name: str, method: str, path: str, body: dict) -> None:
        key = self.create_personal_api_key_with_scopes(["warehouse_view:read"])
        with patch(_SEND) as send:
            assert self._call(method, path, key, body).status_code == status.HTTP_403_FORBIDDEN
        send.assert_not_called()

    def _key(self, scoped_teams: list[int] | None) -> str:
        key_value = generate_random_token_personal()
        PersonalAPIKey.objects.create(
            label="Test Key",
            user=self.user,
            secure_value=hash_key_value(key_value),
            scopes=["warehouse_view:read"],
            scoped_teams=scoped_teams,
        )
        return key_value

    @parameterized.expand(
        [
            (f"{read} {key}", path, scoped, expected)
            for read, path in (
                ("usage", "usage/"),
                ("queries", "queries/"),
                ("queries of another project", "queries/?team_id={other}"),
                ("storage", "storage/"),
                ("settings", "settings/"),
            )
            for key, scoped, expected in (
                ("scoped key", True, status.HTTP_403_FORBIDDEN),
                ("unscoped key", False, status.HTTP_200_OK),
            )
        ]
    )
    def test_warehouse_wide_reads_need_a_key_that_reaches_every_project(
        self, _name: str, path: str, scoped: bool, expected: int
    ) -> None:
        other = Team.objects.create(organization=self.organization, name="Other")
        key = self._key([self.team.pk] if scoped else None)

        def send(method: str, request_path: str, **kwargs: Any) -> TranslatedResponse:
            for suffix, body in (("/usage", USAGE_BODY), ("/queries", HISTORY_BODY), ("/tables", STORAGE_BODY)):
                if request_path.endswith(suffix):
                    return TranslatedResponse(200, body)
            return TranslatedResponse(200, {"status": "idle"})

        with patch(_SEND, side_effect=send):
            response = self._call("get", path.format(other=other.pk), key)
        assert response.status_code == expected
