from typing import Any, cast

from posthog.test.base import APIBaseTest
from unittest.mock import patch

from django.apps import apps

from rest_framework import status

from posthog.api.file_system.canvas_source import CANVAS_COMPONENT_PATH, CANVAS_ENTRY_HTML
from posthog.models.file_system.file_system import FileSystem
from posthog.models.oauth import OAuthApplication
from posthog.models.organization import Organization
from posthog.models.team import Team
from posthog.temporal.oauth import (
    ARRAY_APP_CLIENT_ID_DEV,
    ARRAY_APP_CLIENT_ID_EU,
    ARRAY_APP_CLIENT_ID_US,
    create_oauth_access_token_for_user,
)

CODE_V1 = 'import React from "react";\nexport default () => <div>v1</div>;\n'
CODE_V2 = 'import React from "react";\nexport default () => <div>v2</div>;\n'


class TestDesktopCanvasSourceAPI(APIBaseTest):
    def setUp(self):
        super().setUp()
        # Staff gate mirrors the desktop/web file system beta gating.
        self.user.is_staff = True
        self.user.save()

    def _base_url(self) -> str:
        return f"/api/projects/{self.team.id}/desktop_file_system/"

    def _create_channel(self, path: str = "MyChannel") -> str:
        response = self.client.post(self._base_url(), {"path": path, "type": "folder"})
        self.assertEqual(response.status_code, status.HTTP_201_CREATED, response.json())
        return cast(str, response.json()["id"])

    def _create_canvas(self, channel_id: str, name: str = "MyCanvas") -> dict[str, Any]:
        response = self.client.post(f"{self._base_url()}canvases/", {"name": name, "channel_id": channel_id})
        self.assertEqual(response.status_code, status.HTTP_201_CREATED, response.json())
        return cast(dict[str, Any], response.json())

    def _project(self, code: str) -> dict[str, Any]:
        return {
            "schemaVersion": 1,
            "files": {CANVAS_COMPONENT_PATH: code},
            "entryHtml": CANVAS_ENTRY_HTML,
            "dependencies": {"react": "19.0.0"},
            "canvasSdkVersion": "0.1.0",
        }

    def test_create_read_validate_publish_edit_loop(self):
        # The full loop a generic task follows: create a canvas, read its source,
        # validate, publish guarded on the empty head, then edit guarded on the
        # returned version. Breaking any hand-off breaks agent canvas authoring.
        channel_id = self._create_channel()
        canvas = self._create_canvas(channel_id)
        canvas_id = canvas["id"]
        self.assertEqual(canvas["name"], "MyCanvas")
        self.assertEqual(canvas["channel_id"], channel_id)
        self.assertIsNone(canvas["current_version_id"])

        source = self.client.get(f"{self._base_url()}{canvas_id}/canvas/source/").json()
        self.assertIsNone(source["current_version_id"])
        self.assertEqual(source["project"]["files"][CANVAS_COMPONENT_PATH], "")
        self.assertEqual(source["project"]["entryHtml"], CANVAS_ENTRY_HTML)

        validated = self.client.post(
            f"{self._base_url()}{canvas_id}/canvas/validate/", {"project": self._project(CODE_V1)}, format="json"
        ).json()
        self.assertTrue(validated["valid"], validated)

        published = self.client.post(
            f"{self._base_url()}{canvas_id}/canvas/publish/",
            {"project": self._project(CODE_V1), "prompt": "first build", "expected_current_version_id": None},
            format="json",
        )
        self.assertEqual(published.status_code, status.HTTP_200_OK, published.json())
        v1 = published.json()["current_version_id"]
        self.assertEqual(published.json()["canvas"]["version_count"], 1)

        meta = cast(dict, FileSystem.objects.get(id=canvas_id).meta)
        self.assertEqual(meta["code"], CODE_V1)
        self.assertEqual(meta["currentVersionId"], v1)
        self.assertEqual(meta["versions"][0]["prompt"], "first build")
        # Creation-time meta keys survive the publish merge.
        self.assertEqual(meta["channelId"], channel_id)

        edited = self.client.post(
            f"{self._base_url()}{canvas_id}/canvas/publish/",
            {"project": self._project(CODE_V2), "expected_current_version_id": v1},
            format="json",
        )
        self.assertEqual(edited.status_code, status.HTTP_200_OK, edited.json())
        meta = cast(dict, FileSystem.objects.get(id=canvas_id).meta)
        self.assertEqual([v["code"] for v in meta["versions"]], [CODE_V1, CODE_V2])

        source = self.client.get(f"{self._base_url()}{canvas_id}/canvas/source/").json()
        self.assertEqual(source["project"]["files"][CANVAS_COMPONENT_PATH], CODE_V2)
        self.assertEqual(source["current_version_id"], meta["currentVersionId"])

    def test_stale_guarded_source_publish_conflicts_and_leaves_canvas_untouched(self):
        channel_id = self._create_channel()
        canvas_id = self._create_canvas(channel_id)["id"]
        self.client.post(
            f"{self._base_url()}{canvas_id}/canvas/publish/", {"project": self._project(CODE_V1)}, format="json"
        )
        head = cast(dict, FileSystem.objects.get(id=canvas_id).meta)["currentVersionId"]

        response = self.client.post(
            f"{self._base_url()}{canvas_id}/canvas/publish/",
            {"project": self._project(CODE_V2), "expected_current_version_id": "not-the-head"},
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_409_CONFLICT, response.json())
        self.assertEqual(response.json()["code"], "version_conflict")
        self.assertEqual(response.json()["current_version_id"], head)
        meta = cast(dict, FileSystem.objects.get(id=canvas_id).meta)
        self.assertEqual(meta["code"], CODE_V1)
        self.assertEqual(len(meta["versions"]), 1)

    def test_invalid_project_publish_returns_diagnostics_and_publishes_nothing(self):
        channel_id = self._create_channel()
        canvas_id = self._create_canvas(channel_id)["id"]

        bad_project = self._project('import _ from "lodash";\n' + CODE_V1)
        response = self.client.post(
            f"{self._base_url()}{canvas_id}/canvas/publish/", {"project": bad_project}, format="json"
        )

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST, response.json())
        body = response.json()
        self.assertEqual(body["code"], "invalid_source_project")
        self.assertIn("import_not_allowed", [d["code"] for d in body["diagnostics"]])
        meta = cast(dict, FileSystem.objects.get(id=canvas_id).meta)
        self.assertNotIn("code", meta)
        self.assertNotIn("versions", meta)

    def test_validate_reports_errors_without_mutating_the_canvas(self):
        channel_id = self._create_channel()
        canvas_id = self._create_canvas(channel_id)["id"]
        before = FileSystem.objects.get(id=canvas_id).meta

        response = self.client.post(
            f"{self._base_url()}{canvas_id}/canvas/validate/",
            {"project": self._project('const m = await import("https://x.dev/e.js");')},
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK, response.json())
        self.assertFalse(response.json()["valid"])
        self.assertEqual(FileSystem.objects.get(id=canvas_id).meta, before)

    def test_validate_rejects_malformed_body_with_400(self):
        # Wiring guard: the request serializer is actually enforced.
        channel_id = self._create_channel()
        canvas_id = self._create_canvas(channel_id)["id"]

        response = self.client.post(f"{self._base_url()}{canvas_id}/canvas/validate/", {}, format="json")

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_canvases_list_scopes_to_channel_and_team(self):
        channel_id = self._create_channel("ChannelA")
        other_channel_id = self._create_channel("ChannelB")
        in_channel = self._create_canvas(channel_id, name="In A")["id"]
        self._create_canvas(other_channel_id, name="In B")

        # A same-path canvas in another team must never leak into this team's list.
        other_org = Organization.objects.create(name="other")
        other_team = Team.objects.create(organization=other_org, name="other")
        FileSystem.objects.create(team=other_team, path="ChannelA/Foreign", type="dashboard", surface="desktop")

        everything = self.client.get(f"{self._base_url()}canvases/").json()
        self.assertEqual({c["name"] for c in everything}, {"In A", "In B"})

        filtered = self.client.get(f"{self._base_url()}canvases/", {"channel_id": channel_id}).json()
        self.assertEqual([c["id"] for c in filtered], [in_channel])

    def test_create_canvas_rejects_unknown_channel(self):
        response = self.client.post(
            f"{self._base_url()}canvases/",
            {"name": "Orphan", "channel_id": "00000000-0000-0000-0000-000000000000"},
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST, response.json())

    def test_non_uuid_channel_id_is_a_client_error_not_a_500(self):
        # Agents pass arbitrary strings; a malformed id must map to 400/404, not
        # bubble the UUID-field ValidationError as a 500.
        create = self.client.post(f"{self._base_url()}canvases/", {"name": "Orphan", "channel_id": "not-a-uuid"})
        self.assertEqual(create.status_code, status.HTTP_400_BAD_REQUEST, create.content)

        listed = self.client.get(f"{self._base_url()}canvases/", {"channel_id": "not-a-uuid"})
        self.assertEqual(listed.status_code, status.HTTP_404_NOT_FOUND, listed.content)

    def test_source_endpoints_reject_non_dashboard_rows(self):
        channel_id = self._create_channel()

        response = self.client.get(f"{self._base_url()}{channel_id}/canvas/source/")

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST, response.json())

    def test_legacy_single_file_publish_route_is_removed(self):
        channel_id = self._create_channel()
        canvas_id = self._create_canvas(channel_id)["id"]

        response = self.client.patch(f"{self._base_url()}{canvas_id}/canvas/", {"code": CODE_V1})

        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)
        self.assertNotIn("code", cast(dict, FileSystem.objects.get(id=canvas_id).meta))

    def _authenticate_as_sandbox(self) -> None:
        for client_id in (ARRAY_APP_CLIENT_ID_DEV, ARRAY_APP_CLIENT_ID_US, ARRAY_APP_CLIENT_ID_EU):
            OAuthApplication.objects.get_or_create(
                client_id=client_id,
                defaults={
                    "name": "Array Test App",
                    "client_type": OAuthApplication.CLIENT_PUBLIC,
                    "authorization_grant_type": OAuthApplication.GRANT_AUTHORIZATION_CODE,
                    "redirect_uris": "https://app.posthog.com/callback",
                    "algorithm": "RS256",
                },
            )
        token = create_oauth_access_token_for_user(self.user, self.team.id, scopes="full")
        self.client.logout()
        self.client.credentials(HTTP_AUTHORIZATION=f"Bearer {token}")

    @patch("products.tasks.backend.facade.api.posthoganalytics.feature_enabled", return_value=True)
    def test_first_source_publish_from_task_announces_in_thread(self, _flag):
        # The new publish path must announce a canvas's first publish in the
        # generating task's thread exactly like the legacy PATCH path does.
        Task = apps.get_model("tasks", "Task")
        task = Task.objects.create(
            team=self.team,
            title="Generate canvas",
            description="",
            origin_product=Task.OriginProduct.USER_CREATED,
            created_by=self.user,
        )
        channel_id = self._create_channel()
        canvas_id = self._create_canvas(channel_id)["id"]
        self._authenticate_as_sandbox()

        self.client.post(
            f"{self._base_url()}{canvas_id}/canvas/publish/",
            {"project": self._project(CODE_V1)},
            format="json",
            HTTP_X_POSTHOG_TASK_ID=str(task.id),
        )

        TaskThreadMessage = apps.get_model("tasks", "TaskThreadMessage")
        self.assertEqual(TaskThreadMessage.objects.for_team(self.team.id).filter(task=task).count(), 1)
