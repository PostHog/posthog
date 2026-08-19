from posthog.test.base import APIBaseTest
from unittest.mock import patch

from django.test import SimpleTestCase

from parameterized import parameterized
from rest_framework import status
from rest_framework.exceptions import ValidationError
from rest_framework.test import APIClient

from posthog.models.team.team import Team

from products.conversations.backend.api.ticket_filters import TicketViewFiltersSerializer
from products.conversations.backend.api.ticket_view_folders import normalize_folder, reparent_folder
from products.conversations.backend.api.ticket_views import MoveFolderRequestSerializer, TicketViewFiltersField
from products.conversations.backend.models import TicketView, TicketViewFavorite


class TestTicketViewAPI(APIBaseTest):
    base_url: str

    def setUp(self):
        super().setUp()
        self.base_url = f"/api/environments/{self.team.pk}/conversations/views/"

    def _valid_payload(self, **overrides) -> dict:
        defaults = {
            "name": "Urgent open tickets",
            "filters": {"status": ["new", "open"], "priority": ["high"]},
        }
        defaults.update(overrides)
        return defaults

    def _create_via_api(self, **overrides) -> dict:
        response = self.client.post(self.base_url, self._valid_payload(**overrides), format="json")
        assert response.status_code == status.HTTP_201_CREATED, response.json()
        return response.json()

    # --- CRUD ---

    @patch("products.conversations.backend.api.ticket_views.report_user_action")
    def test_create(self, mock_report):
        data = self._create_via_api()
        assert data["name"] == "Urgent open tickets"
        assert data["filters"] == {"status": ["new", "open"], "priority": ["high"]}
        assert data["short_id"] is not None
        assert data["created_by"]["id"] == self.user.pk

        mock_report.assert_called_once()
        assert mock_report.call_args[0][1] == "ticket view created"
        assert mock_report.call_args[0][2]["name"] == "Urgent open tickets"
        assert mock_report.call_args[0][2]["has_filters"] is True

    def test_list(self):
        self._create_via_api(name="View 1")
        self._create_via_api(name="View 2")

        response = self.client.get(self.base_url)
        assert response.status_code == status.HTTP_200_OK
        results = response.json()["results"]
        assert len(results) == 2
        assert {r["name"] for r in results} == {"View 1", "View 2"}

    def test_retrieve(self):
        created = self._create_via_api()

        response = self.client.get(f"{self.base_url}{created['short_id']}/")
        assert response.status_code == status.HTTP_200_OK
        assert response.json()["short_id"] == created["short_id"]
        assert response.json()["name"] == "Urgent open tickets"

    @patch("products.conversations.backend.api.ticket_views.report_user_action")
    def test_delete(self, mock_report):
        created = self._create_via_api()
        mock_report.reset_mock()

        response = self.client.delete(f"{self.base_url}{created['short_id']}/")
        assert response.status_code == status.HTTP_204_NO_CONTENT
        assert not TicketView.objects.filter(pk=created["id"]).exists()

        mock_report.assert_called_once()
        assert mock_report.call_args[0][1] == "ticket view deleted"

    @patch("products.conversations.backend.api.ticket_views.report_user_action")
    def test_update_name_keeps_short_id_and_filters(self, mock_report):
        created = self._create_via_api()
        mock_report.reset_mock()

        response = self.client.patch(
            f"{self.base_url}{created['short_id']}/",
            {"name": "Renamed", "short_id": "hijacked"},
            format="json",
        )
        assert response.status_code == status.HTTP_200_OK
        data = response.json()
        assert data["name"] == "Renamed"
        assert data["short_id"] == created["short_id"]
        assert data["filters"] == created["filters"]

        mock_report.assert_called_once()
        assert mock_report.call_args[0][1] == "ticket view updated"

    def test_put_not_allowed(self):
        created = self._create_via_api()
        response = self.client.put(
            f"{self.base_url}{created['short_id']}/",
            {"name": "Replaced"},
            format="json",
        )
        assert response.status_code == status.HTTP_405_METHOD_NOT_ALLOWED
        assert TicketView.objects.get(pk=created["id"]).filters == created["filters"]

    def test_update_filters_keeps_name(self):
        created = self._create_via_api()

        new_filters = {
            "status": ["resolved"],
            "assignee": {"type": "role", "id": "9c9a4c7e-9ab5-4f30-9b74-3d1e9f9d3a01"},
        }
        response = self.client.patch(
            f"{self.base_url}{created['short_id']}/",
            {"filters": new_filters},
            format="json",
        )
        assert response.status_code == status.HTTP_200_OK
        assert response.json()["filters"] == new_filters
        assert response.json()["name"] == created["name"]

    # --- Filters are optional ---

    def test_create_with_empty_filters(self):
        data = self._create_via_api(filters={})
        assert data["filters"] == {}

    def test_create_with_no_filters(self):
        response = self.client.post(self.base_url, {"name": "Minimal view"}, format="json")
        assert response.status_code == status.HTTP_201_CREATED
        assert response.json()["filters"] == {}

    def test_create_with_complex_filters(self):
        filters = {
            "status": ["new", "open"],
            "priority": ["high", "medium"],
            "channel": "slack",
            "sla": "breached",
            "assignee": [{"type": "user", "id": 1}],
            "tags": ["bug", "urgent"],
            "dateFrom": "-7d",
            "dateTo": None,
            "sorting": {"columnKey": "updated_at", "order": -1},
        }
        data = self._create_via_api(filters=filters)
        assert data["filters"] == filters

    # --- Validation ---

    @parameterized.expand(
        [
            ("missing_name", {"filters": {}}),
            ("blank_name", {"name": "", "filters": {}}),
        ]
    )
    def test_create_rejects_invalid_name(self, _label, payload):
        response = self.client.post(self.base_url, payload, format="json")
        assert response.status_code == status.HTTP_400_BAD_REQUEST

    @parameterized.expand(
        [
            ("bad_status", {"status": ["bogus"]}),
            # Only rejected in strict mode, so this case proves the write path passes strict_writes.
            ("assignee_string_token", {"assignee": ["user:1"]}),
        ]
    )
    def test_create_rejects_invalid_filter_values(self, _label, filters):
        # Wiring guard: the endpoint must run TicketViewFiltersSerializer, so a filter
        # value the canonical shape rejects never reaches the database.
        response = self.client.post(
            self.base_url,
            {"name": "Bad view", "filters": filters},
            format="json",
        )
        assert response.status_code == status.HTTP_400_BAD_REQUEST
        assert not TicketView.objects.filter(team=self.team).exists()

    def test_unknown_filter_keys_survive_round_trip(self):
        # Filters are stored raw, so keys a newer frontend adds must not be dropped
        # by an older backend's stricter validation.
        data = self._create_via_api(filters={"status": ["open"], "futureKey": True})
        assert data["filters"] == {"status": ["open"], "futureKey": True}

    # --- Read-only fields ---

    def test_short_id_ignored_on_create(self):
        data = self._create_via_api(short_id="custom123")
        assert data["short_id"] != "custom123"

    # --- Team isolation ---

    def test_list_only_own_team(self):
        team2 = Team.objects.create(organization=self.organization, name="Team 2")
        TicketView.objects.create(team=team2, name="Other team view", created_by=self.user)
        self._create_via_api(name="My view")

        response = self.client.get(self.base_url)
        results = response.json()["results"]
        assert len(results) == 1
        assert results[0]["name"] == "My view"

    def test_cannot_retrieve_other_teams_view(self):
        team2 = Team.objects.create(organization=self.organization, name="Team 2")
        other_view = TicketView.objects.create(team=team2, name="Other", created_by=self.user)

        response = self.client.get(f"{self.base_url}{other_view.short_id}/")
        assert response.status_code == status.HTTP_404_NOT_FOUND

    def test_cannot_update_other_teams_view(self):
        team2 = Team.objects.create(organization=self.organization, name="Team 2")
        other_view = TicketView.objects.create(team=team2, name="Other", created_by=self.user)

        response = self.client.patch(f"{self.base_url}{other_view.short_id}/", {"name": "Hacked"}, format="json")
        assert response.status_code == status.HTTP_404_NOT_FOUND
        other_view.refresh_from_db()
        assert other_view.name == "Other"

    def test_cannot_delete_other_teams_view(self):
        team2 = Team.objects.create(organization=self.organization, name="Team 2")
        other_view = TicketView.objects.create(team=team2, name="Other", created_by=self.user)

        response = self.client.delete(f"{self.base_url}{other_view.short_id}/")
        assert response.status_code == status.HTTP_404_NOT_FOUND
        assert TicketView.objects.filter(pk=other_view.id).exists()

    # --- Personal favorites ---

    def test_favorite_and_unfavorite(self):
        created = self._create_via_api()

        response = self.client.patch(f"{self.base_url}{created['short_id']}/", {"is_favorited": True}, format="json")
        assert response.status_code == status.HTTP_200_OK
        assert response.json()["is_favorited"] is True
        assert (
            TicketViewFavorite.objects.for_team(self.team.pk)
            .filter(ticket_view_id=created["id"], user=self.user)
            .count()
            == 1
        )

        # Idempotent: favoriting again doesn't create a second row
        self.client.patch(f"{self.base_url}{created['short_id']}/", {"is_favorited": True}, format="json")
        assert (
            TicketViewFavorite.objects.for_team(self.team.pk)
            .filter(ticket_view_id=created["id"], user=self.user)
            .count()
            == 1
        )

        response = self.client.patch(f"{self.base_url}{created['short_id']}/", {"is_favorited": False}, format="json")
        assert response.json()["is_favorited"] is False
        assert (
            not TicketViewFavorite.objects.for_team(self.team.pk)
            .filter(ticket_view_id=created["id"], user=self.user)
            .exists()
        )

    @parameterized.expand([("favorited", True), ("not_favorited", False)])
    def test_create_with_favorited_flag(self, _label, favorited):
        data = self._create_via_api(is_favorited=favorited)
        assert data["is_favorited"] is favorited
        assert (
            TicketViewFavorite.objects.for_team(self.team.pk).filter(ticket_view_id=data["id"], user=self.user).exists()
            is favorited
        )

    def test_favorites_are_personal_to_each_user(self):
        created = self._create_via_api()
        self.client.patch(f"{self.base_url}{created['short_id']}/", {"is_favorited": True}, format="json")

        other_user = self._create_user("other@posthog.com")
        other_client = APIClient()
        other_client.force_login(other_user)

        response = other_client.get(self.base_url)
        assert response.json()["results"][0]["is_favorited"] is False

    def test_favorited_views_sort_to_top(self):
        older = self._create_via_api(name="Older")
        self._create_via_api(name="Newer")

        # Default order is newest-first; favoriting the older view must float it up
        self.client.patch(f"{self.base_url}{older['short_id']}/", {"is_favorited": True}, format="json")

        results = self.client.get(self.base_url).json()["results"]
        assert [r["name"] for r in results] == ["Older", "Newer"]
        assert results[0]["is_favorited"] is True

    # --- Folders ---

    def _make_view(self, name: str, folder: str) -> TicketView:
        return TicketView.objects.create(team=self.team, name=name, folder=folder, created_by=self.user)

    def _folders(self) -> dict[str, str]:
        return {view.name: view.folder for view in TicketView.objects.filter(team=self.team)}

    def test_create_with_folder(self):
        data = self._create_via_api(folder="Escalations/EU")
        assert data["folder"] == "Escalations/EU"

        listed = self.client.get(self.base_url).json()["results"]
        assert listed[0]["folder"] == "Escalations/EU"

    def test_create_without_folder_returns_empty_string(self):
        # Root is always "", never null, so clients need no second spelling for "no folder"
        data = self._create_via_api()
        assert data["folder"] == ""

    def test_patch_folder_keeps_name_and_filters(self):
        created = self._create_via_api()

        response = self.client.patch(
            f"{self.base_url}{created['short_id']}/", {"folder": "/Escalations//EU/"}, format="json"
        )
        assert response.status_code == status.HTTP_200_OK
        # Stray leading, trailing, and doubled slashes normalize instead of erroring
        assert response.json()["folder"] == "Escalations/EU"
        assert response.json()["name"] == created["name"]
        assert response.json()["filters"] == created["filters"]
        assert response.json()["short_id"] == created["short_id"]

    @patch("products.conversations.backend.api.ticket_views.report_user_action")
    def test_move_folder_rewrites_subtree(self, mock_report):
        self._make_view("Parent", "Escalations")
        self._make_view("Child", "Escalations/EU")
        mock_report.reset_mock()

        response = self.client.post(
            f"{self.base_url}move_folder/",
            {"from_folder": "Escalations", "to_folder": "Ops/Escalations"},
            format="json",
        )
        assert response.status_code == status.HTTP_200_OK
        assert response.json()["moved"] == 2
        assert response.json()["to_folder"] == "Ops/Escalations"
        assert self._folders() == {"Parent": "Ops/Escalations", "Child": "Ops/Escalations/EU"}

        mock_report.assert_called_once()
        assert mock_report.call_args[0][1] == "ticket view folder moved"
        assert mock_report.call_args[0][2] == {"count": 2, "from_depth": 1, "to_depth": 2}

    def test_move_folder_leaves_name_prefix_siblings_alone(self):
        self._make_view("Moved", "Escalations")
        self._make_view("Nested", "Escalations/EU")
        self._make_view("Spaced", "Escalations EU")
        self._make_view("Suffixed", "EscalationsX")

        response = self.client.post(
            f"{self.base_url}move_folder/", {"from_folder": "Escalations", "to_folder": "Ops"}, format="json"
        )
        assert response.status_code == status.HTTP_200_OK
        assert self._folders() == {
            "Moved": "Ops",
            "Nested": "Ops/EU",
            "Spaced": "Escalations EU",
            "Suffixed": "EscalationsX",
        }

    def test_move_folder_escapes_like_wildcards_in_folder_name(self):
        # "%" and "_" are LIKE metacharacters: unescaped, "100%_done/" would also match "100ZZdone/"
        self._make_view("Moved", "100%_done")
        self._make_view("Nested", "100%_done/EU")
        self._make_view("Decoy", "100ZZdone")
        self._make_view("NestedDecoy", "100ZZdone/EU")

        response = self.client.post(
            f"{self.base_url}move_folder/", {"from_folder": "100%_done", "to_folder": "Archive"}, format="json"
        )
        assert response.status_code == status.HTTP_200_OK
        assert self._folders() == {
            "Moved": "Archive",
            "Nested": "Archive/EU",
            "Decoy": "100ZZdone",
            "NestedDecoy": "100ZZdone/EU",
        }

    def test_move_folder_to_root(self):
        self._make_view("Parent", "Escalations")
        self._make_view("Child", "Escalations/EU")

        response = self.client.post(
            f"{self.base_url}move_folder/", {"from_folder": "Escalations", "to_folder": ""}, format="json"
        )
        assert response.status_code == status.HTTP_200_OK
        # No leading slash left behind on the descendant
        assert self._folders() == {"Parent": "", "Child": "EU"}

    def test_move_folder_rejects_result_past_depth_cap(self):
        deep = "a/b/c/d/e/f/g/h/i"
        self._make_view("Deep", deep)

        response = self.client.post(
            f"{self.base_url}move_folder/", {"from_folder": "a", "to_folder": "x/y/z"}, format="json"
        )
        assert response.status_code == status.HTTP_400_BAD_REQUEST
        assert self._folders() == {"Deep": deep}

    def test_move_folder_rejects_invalid_request(self):
        # Wiring guard: the action must run MoveFolderRequestSerializer, so an invalid move
        # never rewrites a folder. The full rejection matrix lives in TestTicketViewFolderPaths.
        self._make_view("Parent", "Escalations")

        response = self.client.post(
            f"{self.base_url}move_folder/",
            {"from_folder": "Escalations", "to_folder": "Escalations/EU"},
            format="json",
        )
        assert response.status_code == status.HTTP_400_BAD_REQUEST
        assert self._folders() == {"Parent": "Escalations"}

    def test_move_folder_only_touches_own_team(self):
        team2 = Team.objects.create(organization=self.organization, name="Team 2")
        other = TicketView.objects.create(team=team2, name="Other", folder="Escalations", created_by=self.user)
        self._make_view("Mine", "Escalations")

        response = self.client.post(
            f"{self.base_url}move_folder/", {"from_folder": "Escalations", "to_folder": "Ops"}, format="json"
        )
        assert response.status_code == status.HTTP_200_OK
        assert response.json()["moved"] == 1
        assert self._folders() == {"Mine": "Ops"}
        other.refresh_from_db()
        assert other.folder == "Escalations"

    def test_move_folder_missing_folder_404(self):
        response = self.client.post(
            f"{self.base_url}move_folder/", {"from_folder": "Nonexistent", "to_folder": "Ops"}, format="json"
        )
        assert response.status_code == status.HTTP_404_NOT_FOUND

    # --- Auth ---

    def test_unauthorized_access(self):
        client = APIClient()
        response = client.get(self.base_url)
        assert response.status_code == status.HTTP_401_UNAUTHORIZED


class TestTicketViewFiltersValidation(SimpleTestCase):
    # No DB: TicketViewFiltersSerializer validation runs entirely in memory. The wiring
    # guard in TestTicketViewAPI proves the endpoint invokes it.

    @parameterized.expand(
        [
            ("empty", {}),
            (
                "frontend_defaults",
                {
                    "status": [],
                    "priority": [],
                    "channel": "all",
                    "sla": "all",
                    "aiTriageResult": [],
                    "assignee": "all",
                    "tags": [],
                    "tagsMatch": "any",
                    "tagsExclude": [],
                    "sorting": {"columnKey": "updated_at", "order": -1},
                    "search": "",
                },
            ),
            (
                "fully_populated",
                {
                    "status": ["open", "pending"],
                    "priority": ["high", "critical"],
                    "channel": "email",
                    "sla": "at-risk",
                    "aiTriageResult": ["escalated_no_reply", "in_progress"],
                    "assignee": ["me", "unassigned", {"type": "user", "id": 1}, {"type": "role", "id": "abc"}],
                    "tags": ["billing"],
                    "tagsMatch": "all",
                    "tagsExclude": ["spam"],
                    "dateFrom": "-30d",
                    "dateTo": None,
                    "sorting": {"columnKey": "created_at", "order": 1},
                    "search": "refund",
                },
            ),
            ("legacy_single_assignee", {"assignee": {"type": "user", "id": 5}}),
            ("null_sorting", {"sorting": None}),
            ("unknown_keys_ignored", {"futureKey": True}),
        ]
    )
    def test_accepts_saved_view_shapes(self, _label, filters):
        serializer = TicketViewFiltersSerializer(data=filters)
        assert serializer.is_valid(), serializer.errors

    @parameterized.expand(
        [
            ("bad_status", {"status": ["bogus"]}),
            ("bad_channel", {"channel": "phone"}),
            ("bad_sla", {"sla": "late"}),
            ("bad_tags_match", {"tagsMatch": "some"}),
            ("bad_triage_result", {"aiTriageResult": ["nope"]}),
            ("sorting_missing_order", {"sorting": {"columnKey": "updated_at"}}),
            ("search_too_long", {"search": "x" * 201}),
        ]
    )
    def test_rejects_invalid_filter_values(self, _label, filters):
        serializer = TicketViewFiltersSerializer(data=filters)
        assert not serializer.is_valid()

    @parameterized.expand(
        [
            ("string_token", ["user:1"], []),
            ("mixed_entries", ["me", "user:1"], ["me"]),
            ("legacy_all", "all", []),
            ("user_non_numeric_id", [{"type": "user", "id": "abc"}], []),
            ("role_non_uuid_id", [{"type": "role", "id": "not-a-uuid"}], []),
        ]
    )
    def test_lenient_mode_drops_invalid_assignee_entries(self, _label, assignee, expected):
        # The ?view= read path validates stored blobs without strict_writes: a legacy or
        # corrupted assignee entry must not 400 the whole view, just fall away.
        serializer = TicketViewFiltersSerializer(data={"assignee": assignee})
        assert serializer.is_valid(), serializer.errors
        assert serializer.validated_data["assignee"] == expected

    @parameterized.expand(
        [
            ("string_token", ["user:1"]),
            ("single_bogus_string", "bogus"),
            ("unknown_type", [{"type": "team", "id": 1}]),
            ("missing_id", [{"type": "user"}]),
            # An unresolvable id would save a view that silently matches all assignees.
            ("user_non_numeric_id", [{"type": "user", "id": "abc"}]),
            ("role_non_uuid_id", [{"type": "role", "id": "not-a-uuid"}]),
        ]
    )
    def test_strict_writes_rejects_invalid_assignee_entries(self, _label, assignee):
        serializer = TicketViewFiltersSerializer(data={"assignee": assignee}, context={"strict_writes": True})
        assert not serializer.is_valid()
        assert "assignee" in serializer.errors

    def test_strict_writes_accepts_legacy_all_sentinel(self):
        serializer = TicketViewFiltersSerializer(data={"assignee": "all"}, context={"strict_writes": True})
        assert serializer.is_valid(), serializer.errors
        assert serializer.validated_data["assignee"] == []

    def test_field_rejects_oversized_payload(self):
        field = TicketViewFiltersField()
        oversized = {"tags": ["x" * 100] * 150}
        with self.assertRaises(ValidationError) as ctx:
            field.run_validation(oversized)
        assert "too large" in str(ctx.exception)


class TestTicketViewFolderPaths(SimpleTestCase):
    # No DB: folder normalization and reparenting are pure string work, and
    # MoveFolderRequestSerializer's rejections run before the action touches a row. The wiring
    # guards in TestTicketViewAPI prove the endpoint invokes both.

    @parameterized.expand(
        [
            ("root", "", ""),
            ("plain", "Escalations", "Escalations"),
            ("nested", "Escalations/EU", "Escalations/EU"),
            ("leading_and_trailing_slash", "/Escalations/EU/", "Escalations/EU"),
            ("doubled_slash", "Escalations//EU", "Escalations/EU"),
            ("padded_segments", " Escalations / EU ", "Escalations/EU"),
            ("only_slashes", "///", ""),
            # An escaped separator is one segment, so a folder named "Escalations/EU" survives
            ("escaped_separator", "Escalations\\/EU", "Escalations\\/EU"),
        ]
    )
    def test_normalize_folder(self, _label, value, expected):
        assert normalize_folder(value) == expected
        assert normalize_folder(normalize_folder(value)) == expected

    @parameterized.expand(
        [
            ("too_deep", "/".join("abcdefghijk")),
            ("segment_too_long", "x" * 101),
            ("newline_in_segment", "Esca\nlations"),
            ("tab_in_segment", "Esca\tlations"),
        ]
    )
    def test_normalize_folder_rejects(self, _label, value):
        with self.assertRaises(ValidationError):
            normalize_folder(value)

    @parameterized.expand(
        [
            ("exact_match", "Escalations", "Escalations", "Ops", "Ops"),
            ("descendant", "Escalations/EU", "Escalations", "Ops", "Ops/EU"),
            ("deeper_destination", "Escalations/EU", "Escalations", "Ops/Region", "Ops/Region/EU"),
            ("to_root", "Escalations/EU", "Escalations", "", "EU"),
            ("rename_in_place", "Escalations/EU", "Escalations", "Escalated", "Escalated/EU"),
        ]
    )
    def test_reparent_folder(self, _label, folder, from_folder, to_folder, expected):
        assert reparent_folder(folder, from_folder, to_folder) == expected

    @parameterized.expand(
        [
            ("blank_source", {"from_folder": "", "to_folder": "Ops"}),
            ("source_normalizes_to_blank", {"from_folder": "///", "to_folder": "Ops"}),
            ("destination_equals_source", {"from_folder": "Escalations", "to_folder": "Escalations"}),
            ("destination_inside_source", {"from_folder": "Escalations", "to_folder": "Escalations/EU"}),
            ("destination_deep_inside_source", {"from_folder": "a", "to_folder": "a/b/c"}),
            ("missing_destination", {"from_folder": "Escalations"}),
        ]
    )
    def test_move_folder_request_rejects(self, _label, payload):
        assert not MoveFolderRequestSerializer(data=payload).is_valid()

    @parameterized.expand(
        [
            ("sibling_name_prefix", {"from_folder": "Escalations", "to_folder": "EscalationsX"}),
            ("to_root", {"from_folder": "Escalations", "to_folder": ""}),
            ("normalizes_both_sides", {"from_folder": "/Escalations/", "to_folder": "//Ops//"}),
        ]
    )
    def test_move_folder_request_accepts(self, _label, payload):
        serializer = MoveFolderRequestSerializer(data=payload)
        assert serializer.is_valid(), serializer.errors
