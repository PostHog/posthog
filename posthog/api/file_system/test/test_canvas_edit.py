from typing import Any, cast

from posthog.test.base import APIBaseTest

from rest_framework import status

from posthog.api.file_system.canvas_source import CANVAS_COMPONENT_PATH, synthetic_source_project
from posthog.models.file_system.file_system import FileSystem

CODE_V1 = 'import React from "react";\nexport default () => <div>v1</div>;\n'
CODE_V2 = 'import React from "react";\nexport default () => <div>v2</div>;\n'


class TestDesktopCanvasEditAPI(APIBaseTest):
    def setUp(self):
        super().setUp()
        self.user.is_staff = True
        self.user.save()

    def _base_url(self) -> str:
        return f"/api/projects/{self.team.id}/desktop_file_system/"

    def _create_published_canvas(self) -> tuple[str, str]:
        channel = self.client.post(self._base_url(), {"path": "MyChannel", "type": "folder"}).json()
        canvas = self.client.post(
            f"{self._base_url()}canvases/", {"name": "MyCanvas", "channel_id": channel["id"]}
        ).json()
        self.client.post(
            f"{self._base_url()}{canvas['id']}/canvas/publish/",
            {"project": synthetic_source_project({"code": CODE_V1}), "expected_current_version_id": None},
            format="json",
        )
        head = cast(dict, FileSystem.objects.get(id=canvas["id"]).meta)["currentVersionId"]
        return canvas["id"], head

    def _edit(self, canvas_id: str, body: dict[str, Any]) -> Any:
        return self.client.post(f"{self._base_url()}{canvas_id}/canvas/edit/", body, format="json")

    def test_edit_publishes_a_new_guarded_version_without_resending_the_project(self):
        canvas_id, head = self._create_published_canvas()

        response = self._edit(
            canvas_id,
            {
                "operations": [{"path": CANVAS_COMPONENT_PATH, "content": CODE_V2}],
                "prompt": "swap v1 for v2",
                "expected_current_version_id": head,
            },
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK, response.json())
        meta = cast(dict, FileSystem.objects.get(id=canvas_id).meta)
        self.assertEqual(meta["code"], CODE_V2)
        self.assertEqual([v["code"] for v in meta["versions"]], [CODE_V1, CODE_V2])
        self.assertEqual(response.json()["current_version_id"], meta["currentVersionId"])

    def test_edit_refuses_to_run_unguarded(self):
        # A diff edit's meaning depends on its base; without the guard it could
        # silently merge into someone else's newer head. The serializer must
        # reject the request outright.
        canvas_id, _head = self._create_published_canvas()

        response = self._edit(
            canvas_id,
            {"operations": [{"path": CANVAS_COMPONENT_PATH, "content": CODE_V2}]},
        )

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(response.json()["attr"], "expected_current_version_id")
        self.assertEqual(cast(dict, FileSystem.objects.get(id=canvas_id).meta)["code"], CODE_V1)

    def test_stale_edit_conflicts_and_leaves_the_canvas_untouched(self):
        canvas_id, _head = self._create_published_canvas()

        response = self._edit(
            canvas_id,
            {
                "operations": [{"path": CANVAS_COMPONENT_PATH, "content": CODE_V2}],
                "expected_current_version_id": "not-the-head",
            },
        )

        self.assertEqual(response.status_code, status.HTTP_409_CONFLICT, response.json())
        self.assertEqual(response.json()["code"], "version_conflict")
        meta = cast(dict, FileSystem.objects.get(id=canvas_id).meta)
        self.assertEqual(meta["code"], CODE_V1)
        self.assertEqual(len(meta["versions"]), 1)

    def test_deleting_a_missing_file_rejects_the_whole_edit(self):
        canvas_id, head = self._create_published_canvas()

        response = self._edit(
            canvas_id,
            {
                "operations": [
                    {"path": CANVAS_COMPONENT_PATH, "content": CODE_V2},
                    {"path": "src/nonexistent.ts", "content": None},
                ],
                "expected_current_version_id": head,
            },
        )

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST, response.json())
        self.assertEqual(response.json()["diagnostics"][0]["code"], "edit_target_missing")
        # Atomic: the valid operation in the same request published nothing.
        self.assertEqual(cast(dict, FileSystem.objects.get(id=canvas_id).meta)["code"], CODE_V1)

    def test_edit_producing_an_invalid_project_is_rejected_with_diagnostics(self):
        canvas_id, head = self._create_published_canvas()

        response = self._edit(
            canvas_id,
            {
                "operations": [{"path": "../escape.tsx", "content": "x"}],
                "expected_current_version_id": head,
            },
        )

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST, response.json())
        self.assertIn("invalid_path", [d["code"] for d in response.json()["diagnostics"]])
        self.assertEqual(cast(dict, FileSystem.objects.get(id=canvas_id).meta)["code"], CODE_V1)
