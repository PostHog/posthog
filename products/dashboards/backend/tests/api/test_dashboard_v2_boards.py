import json
from pathlib import Path
from typing import Any

from posthog.test.base import APIBaseTest
from unittest.mock import patch

from django.test import SimpleTestCase

from parameterized import parameterized
from rest_framework import status

from posthog.constants import AvailableFeature
from posthog.models.organization import OrganizationMembership
from posthog.models.team import Team
from posthog.models.user import User

from products.access_control.backend.models.access_control import AccessControl
from products.dashboards.backend.facade.contracts import MAX_BOARD_SPEC_BYTES
from products.dashboards.backend.facade.enums import BoardManagedBy
from products.dashboards.backend.models.dashboard_v2_board import DashboardV2Board
from products.dashboards.backend.v2.board_schema import CURRENT_SCHEMA_VERSION, upgrade

_FIXTURES = Path(__file__).parent.parent / "fixtures"


class TestBoardSchemaUpgrade(SimpleTestCase):
    @parameterized.expand([(path.name,) for path in sorted(_FIXTURES.glob("dashboard_v2_board_schema_*.json"))])
    def test_a_stored_board_upgrades_to_the_current_schema_and_keeps_its_content(self, fixture: str) -> None:
        stored = json.loads((_FIXTURES / fixture).read_text())

        upgraded = upgrade(stored)

        assert upgraded["version"] == CURRENT_SCHEMA_VERSION
        assert upgraded["aFieldFromANewerClient"] == {"kept": True}
        assert [tab["id"] for tab in upgraded["tabs"]] == [tab["id"] for tab in stored["tabs"]]
        tiles = upgraded["tabs"][0]["tiles"]
        assert [tile["id"] for tile in tiles] == ["t-stat", "t-shared", "s-more"]
        assert list(upgraded["panels"]) == ["shared-count"] and "widgets" not in upgraded
        nested = tiles[2]["panel"]["tiles"]
        assert all("panel" in tile and "widget" not in tile for tile in [*tiles, *nested])
        assert nested[0]["panel"]["config"] == {"text": "Hello"}


def _nested(value: Any, depth: int) -> Any:
    for _ in range(depth):
        value = {"d": value}
    return value


def _board(title: str = "Kitchen sink", **extra: Any) -> dict:
    return {
        "version": 2,
        "title": title,
        "tabs": [{"id": "main", "title": "Main", "tiles": [{"id": "a", "place": {"x": 0, "y": 0, "w": 6, "h": 4}}]}],
        **extra,
    }


class TestDashboardV2Boards(APIBaseTest):
    def setUp(self) -> None:
        super().setUp()
        self.flag_on = True
        patcher = patch("posthoganalytics.feature_enabled", side_effect=self._flag_enabled)
        patcher.start()
        self.addCleanup(patcher.stop)

    def _flag_enabled(self, flag: str, distinct_id: str, **kwargs: Any) -> bool:
        return self.flag_on and flag in ("dashboard-v2", "dashboard-v2-users")

    def _url(self, uid: str | None = None, team_id: int | None = None) -> str:
        base = f"/api/projects/{team_id or self.team.pk}/dashboard_v2/boards/"
        return f"{base}{uid}/" if uid else base

    def _create(self, spec: Any) -> Any:
        return self.client.post(self._url(), {"spec": spec}, format="json")

    def test_save_load_list_update_and_delete(self) -> None:
        # The tile has no widget: a malformed tile still saves, and the scene shows it as an error tile.
        created = self._create(_board())
        assert created.status_code == status.HTTP_201_CREATED, created.json()
        uid = created.json()["uid"]
        assert created.json()["version"] == 1
        assert created.json()["title"] == "Kitchen sink"

        loaded = self.client.get(self._url(uid))
        assert loaded.status_code == status.HTTP_200_OK
        assert loaded.json()["spec"] == _board()

        listed = self.client.get(self._url()).json()
        assert [row["uid"] for row in listed["results"]] == [uid]
        assert "spec" not in listed["results"][0]

        updated = self.client.put(self._url(uid), {"spec": _board("Renamed"), "base_version": 1}, format="json")
        assert updated.status_code == status.HTTP_200_OK, updated.json()
        assert updated.json()["version"] == 2
        assert updated.json()["title"] == "Renamed"
        assert self.client.get(self._url(uid)).json()["spec"]["title"] == "Renamed"

        assert self.client.delete(self._url(uid)).status_code == status.HTTP_204_NO_CONTENT
        assert self.client.get(self._url(uid)).status_code == status.HTTP_404_NOT_FOUND
        assert self.client.get(self._url()).json()["results"] == []

    def test_list_metadata_comes_from_the_document_and_unknown_fields_are_kept(self) -> None:
        spec = {**_board(tags=["web", "web", 3], folder="Team/Growth"), "aFieldFromANewerClient": {"kept": True}}
        uid = self._create(spec).json()["uid"]

        row = self.client.get(self._url()).json()["results"][0]
        assert (row["tags"], row["folder"], row["managed_by"]) == (["web"], "Team/Growth", "native")
        assert self.client.get(self._url(uid)).json()["spec"]["aFieldFromANewerClient"] == {"kept": True}

    def test_a_builtin_board_cannot_be_changed_or_deleted(self) -> None:
        uid = self._create(_board()).json()["uid"]
        DashboardV2Board.objects.for_team(self.team.pk).filter(uid=uid).update(managed_by=BoardManagedBy.BUILTIN)

        assert self.client.put(self._url(uid), {"spec": _board("x")}, format="json").status_code == 403
        assert self.client.delete(self._url(uid)).status_code == 403
        assert self.client.get(self._url(uid)).json()["title"] == "Kitchen sink"

    def test_update_based_on_an_old_version_is_refused(self) -> None:
        uid = self._create(_board()).json()["uid"]
        self.client.put(self._url(uid), {"spec": _board("First"), "base_version": 1}, format="json")

        stale = self.client.put(self._url(uid), {"spec": _board("Second"), "base_version": 1}, format="json")

        assert stale.status_code == status.HTTP_409_CONFLICT
        assert stale.json()["code"] == "version_conflict"
        board = self.client.get(self._url(uid)).json()
        assert (board["version"], board["title"]) == (2, "First")

    @parameterized.expand(
        [
            ("not_an_object", [1, 2]),
            ("classic_dashboard_version", {**_board(), "version": 1}),
            ("newer_schema_than_this_server", {**_board(), "version": CURRENT_SCHEMA_VERSION + 1}),
            ("no_schema_version", {"title": "x", "tabs": []}),
            ("too_large", _board(description="x" * MAX_BOARD_SPEC_BYTES)),
            ("nul_character", {**_board(), "tabs": [{"id": "t", "tiles": [{"id": "a\x00b"}]}]}),
            ("nul_character_deeply_nested", _board(extra=_nested({"note": "a\x00b"}, depth=600))),
            ("not_a_finite_number", _board(extra={"ratio": float("nan")})),
            ("nested_too_deep", _board(extra=_nested("x", depth=20000))),
        ]
    )
    def test_rejects_a_document_that_is_not_a_version_2_board(self, _name: str, spec: Any) -> None:
        response = self._create(spec)

        assert response.status_code == status.HTTP_400_BAD_REQUEST
        assert response.json()["attr"] == "spec"

    @parameterized.expand([("in_a_key", '{"\\ud800": "x"}'), ("in_a_value", '{"note": "a\\udc00"}')])
    def test_rejects_an_unpaired_surrogate(self, _name: str, extra: str) -> None:
        # Sent as raw JSON, because the test client cannot encode a lone surrogate itself.
        body = '{"spec": {"version": 2, "title": "x", "tabs": [], "extra": ' + extra + "}}"
        response = self.client.post(self._url(), body, content_type="application/json")

        assert response.status_code == status.HTTP_400_BAD_REQUEST, response.content
        assert response.json()["attr"] == "spec"

    def test_another_teams_board_is_not_found(self) -> None:
        uid = self._create(_board()).json()["uid"]
        other_team = Team.objects.create(organization=self.organization, name="Other")

        assert self.client.get(self._url(uid, other_team.pk)).status_code == status.HTTP_404_NOT_FOUND
        assert self.client.get(self._url(team_id=other_team.pk)).json()["results"] == []
        patched = self.client.put(self._url(uid, other_team.pk), {"spec": _board("Taken")}, format="json")
        assert patched.status_code == status.HTTP_404_NOT_FOUND
        assert self.client.delete(self._url(uid, other_team.pk)).status_code == status.HTTP_404_NOT_FOUND
        assert self.client.get(self._url(uid)).json()["title"] == "Kitchen sink"

    def test_a_child_environment_of_the_project_is_not_found(self) -> None:
        child = Team.objects.create(organization=self.organization, project=self.team.project, name="Child")

        assert self.client.get(self._url(team_id=child.pk)).status_code == status.HTTP_404_NOT_FOUND
        assert self.client.post(self._url(team_id=child.pk), {"spec": _board()}, format="json").status_code == 404

    def _member(self) -> User:
        self.organization.available_product_features = [
            {"key": AvailableFeature.ACCESS_CONTROL, "name": AvailableFeature.ACCESS_CONTROL}
        ]
        self.organization.save()
        member = User.objects.create_and_join(self.organization, "member@posthog.com", "password")
        OrganizationMembership.objects.filter(user=member).update(level=OrganizationMembership.Level.MEMBER)
        return member

    def test_an_object_rule_of_none_hides_a_board_from_other_members(self) -> None:
        shown = self._create(_board("Shown")).json()
        hidden = self._create(_board("Hidden")).json()
        AccessControl.objects.create(
            team=self.team, resource="dashboard", resource_id=hidden["id"], access_level="none"
        )
        self.client.force_login(self._member())

        assert [row["uid"] for row in self.client.get(self._url()).json()["results"]] == [shown["uid"]]
        assert self.client.get(self._url(hidden["uid"])).status_code in (403, 404)
        patched = self.client.put(self._url(hidden["uid"]), {"spec": _board("x")}, format="json")
        assert patched.status_code in (403, 404)

        admin = User.objects.create_and_join(self.organization, "admin@posthog.com", "password")
        OrganizationMembership.objects.filter(user=admin).update(level=OrganizationMembership.Level.ADMIN)
        self.client.force_login(admin)
        assert {row["uid"] for row in self.client.get(self._url()).json()["results"]} == {shown["uid"], hidden["uid"]}

    def test_without_dashboard_access_a_member_sees_only_granted_and_own_boards(self) -> None:
        granted = self._create(_board("Granted")).json()
        self._create(_board("Not granted"))
        member = self._member()
        AccessControl.objects.create(team=self.team, resource="dashboard", access_level="none")
        AccessControl.objects.create(
            team=self.team,
            resource="dashboard",
            resource_id=granted["id"],
            access_level="viewer",
            organization_member=OrganizationMembership.objects.get(user=member),
        )
        self.client.force_login(member)

        assert [row["title"] for row in self.client.get(self._url()).json()["results"]] == ["Granted"]
        assert self.client.get(self._url(granted["uid"])).status_code == status.HTTP_200_OK

    def test_endpoints_are_not_found_without_the_flag(self) -> None:
        uid = self._create(_board()).json()["uid"]
        self.flag_on = False

        assert self.client.get(self._url()).status_code == status.HTTP_404_NOT_FOUND
        assert self.client.get(self._url(uid)).status_code == status.HTTP_404_NOT_FOUND
        assert self._create(_board()).status_code == status.HTTP_404_NOT_FOUND
