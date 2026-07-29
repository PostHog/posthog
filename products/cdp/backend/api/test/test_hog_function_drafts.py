from posthog.test.base import APIBaseTest
from unittest.mock import patch

from parameterized import parameterized
from rest_framework import status

from products.cdp.backend.models.hog_functions.hog_function import HogFunction
from products.cdp.backend.models.hog_functions.hog_function_revision import HogFunctionRevision

FLAG_PATH = "products.cdp.backend.api.hog_function.use_destinations_revisions"
RELOAD_PATH = "products.cdp.backend.models.hog_functions.hog_function.reload_hog_functions_on_workers"

LIVE_HOG = "fetch(inputs.url);"
EDITED_HOG = "fetch(inputs.url, {'method': 'PUT'});"

BASE_FUNCTION = {
    "name": "Webhook",
    "type": "destination",
    "hog": LIVE_HOG,
    "enabled": True,
    "inputs_schema": [
        {"key": "url", "type": "string", "label": "Webhook URL", "required": True},
        {"key": "token", "type": "string", "label": "Token", "secret": True, "required": False},
    ],
    "inputs": {"url": {"value": "https://example.com/live"}, "token": {"value": "live-token"}},
}


class DraftTestCase(APIBaseTest):
    def setUp(self):
        super().setUp()
        flag = patch(FLAG_PATH, return_value=True)
        flag.start()
        self.addCleanup(flag.stop)

    def _url(self, function_id: str = "", suffix: str = "") -> str:
        base = f"/api/projects/{self.team.id}/hog_functions/"
        return f"{base}{function_id}{suffix}" if function_id else base

    def _create(self, **overrides) -> str:
        response = self.client.post(self._url(), data={**BASE_FUNCTION, **overrides})
        assert response.status_code == status.HTTP_201_CREATED, response.json()
        return response.json()["id"]

    def _agent_patch(self, function_id: str, payload: dict):
        return self.client.patch(self._url(function_id), payload, headers={"x-posthog-client": "mcp"})

    def _stage(self, function_id: str, payload: dict) -> dict:
        response = self._agent_patch(function_id, payload)
        assert response.status_code == status.HTTP_200_OK, response.json()
        return response.json()

    def _live_edit(self, function_id: str, payload: dict):
        response = self.client.patch(self._url(function_id), payload)
        assert response.status_code == status.HTTP_200_OK, response.json()
        return response.json()

    def _revisions(self, function_id: str):
        return HogFunctionRevision.objects.for_team(self.team.id).filter(hog_function_id=function_id)


class TestHogFunctionDrafts(DraftTestCase):
    def _preview_publish(self, function_id: str) -> dict:
        response = self.client.post(self._url(function_id, "/publish"), {})
        assert response.status_code == status.HTTP_200_OK, response.json()
        return response.json()

    def _publish(self, function_id: str):
        preview = self._preview_publish(function_id)
        return self.client.post(
            self._url(function_id, "/publish"),
            {"confirm": True, "confirm_token": preview["confirm_token"]},
        )

    def test_agent_config_edit_to_enabled_function_stages_a_draft(self):
        function_id = self._create()

        with patch(RELOAD_PATH) as mock_reload:
            response = self._stage(function_id, {"hog": EDITED_HOG})

        assert response["draft"]["hog"] == EDITED_HOG
        assert response["draft_updated_at"] is not None
        # The whole point: workers keep running the config a human last approved.
        mock_reload.assert_not_called()
        assert HogFunction.objects.get(id=function_id).hog == LIVE_HOG

    @parameterized.expand(
        [
            # An agent can't stage a draft on a function that isn't running, and the web builder
            # saves what the person just reviewed, so neither routes to a draft.
            ("disabled_function", True, {"enabled": False}, True),
            ("web_caller", False, {}, True),
            # The flag is the kill switch: off means the pre-draft behavior, edits apply live.
            ("flag_off", True, {}, False),
        ]
    )
    def test_config_edit_applies_live(self, _name: str, from_agent: bool, overrides: dict, flag_on: bool):
        function_id = self._create(**overrides)

        with patch(FLAG_PATH, return_value=flag_on):
            response = (
                self._agent_patch(function_id, {"hog": EDITED_HOG})
                if from_agent
                else self.client.patch(self._url(function_id), {"hog": EDITED_HOG})
            )

        assert response.status_code == status.HTTP_200_OK, response.json()
        assert response.json()["draft"] is None
        assert HogFunction.objects.get(id=function_id).hog == EDITED_HOG

    def test_agent_metadata_in_a_config_edit_still_applies_live(self):
        function_id = self._create()

        self._stage(function_id, {"name": "Renamed", "enabled": False, "filters": {"source": "events"}})

        function = HogFunction.objects.get(id=function_id)
        assert function.name == "Renamed"
        assert function.enabled is False
        assert function.draft is not None
        assert function.draft["filters"]["source"] == "events"

    def test_metadata_only_agent_edit_stages_nothing(self):
        function_id = self._create()

        # The serializer fills inputs/inputs_schema/filters defaults in; that must not read as a
        # config edit and strand a no-op draft on the function.
        self._stage(function_id, {"description": "Now documented"})

        function = HogFunction.objects.get(id=function_id)
        assert function.draft is None
        assert function.description == "Now documented"

    def test_a_later_draft_edit_keeps_earlier_staged_config(self):
        function_id = self._create()
        self._stage(function_id, {"inputs": {"url": {"value": "https://example.com/staged"}}})

        draft = self._stage(function_id, {"hog": EDITED_HOG})["draft"]

        assert draft["inputs"]["url"]["value"] == "https://example.com/staged"
        assert draft["hog"] == EDITED_HOG

    def test_publish_preview_reports_changed_fields_without_applying(self):
        function_id = self._create()
        self._stage(function_id, {"hog": EDITED_HOG})

        preview = self._preview_publish(function_id)

        assert preview["published"] is False
        assert preview["changed_fields"] == ["hog"]
        assert preview["confirm_token"]
        assert HogFunction.objects.get(id=function_id).hog == LIVE_HOG

    def test_publish_applies_the_draft_and_bumps_the_version(self):
        function_id = self._create()
        self._stage(function_id, {"hog": EDITED_HOG})

        response = self._publish(function_id)

        assert response.status_code == status.HTTP_200_OK, response.json()
        assert response.json()["published"] is True
        function = HogFunction.objects.get(id=function_id)
        assert function.hog == EDITED_HOG
        assert function.draft is None
        assert function.draft_updated_at is None
        assert function.version == 2
        # Publish revalidates rather than trusting the stored blob, so bytecode is recompiled.
        assert function.bytecode is not None
        assert self._revisions(function_id).count() == 2

    @parameterized.expand(
        [
            ("no_token", {"confirm": True}, status.HTTP_400_BAD_REQUEST),
            ("nothing_staged", {}, status.HTTP_400_BAD_REQUEST),
        ]
    )
    def test_publish_is_rejected(self, name: str, payload: dict, expected: int):
        function_id = self._create()
        if name != "nothing_staged":
            self._stage(function_id, {"hog": EDITED_HOG})

        response = self.client.post(self._url(function_id, "/publish"), payload)

        assert response.status_code == expected, response.json()
        assert HogFunction.objects.get(id=function_id).hog == LIVE_HOG

    def test_publish_with_a_token_from_before_the_latest_edit_conflicts(self):
        function_id = self._create()
        self._stage(function_id, {"hog": EDITED_HOG})
        stale_token = self._preview_publish(function_id)["confirm_token"]
        self._stage(function_id, {"hog": "fetch(inputs.url, {'method': 'PATCH'});"})

        response = self.client.post(self._url(function_id, "/publish"), {"confirm": True, "confirm_token": stale_token})

        assert response.status_code == status.HTTP_409_CONFLICT, response.json()
        assert HogFunction.objects.get(id=function_id).hog == LIVE_HOG

    def test_discard_draft_clears_the_draft_and_is_idempotent(self):
        function_id = self._create()
        self._stage(function_id, {"hog": EDITED_HOG})

        first = self.client.post(self._url(function_id, "/discard_draft"))
        second = self.client.post(self._url(function_id, "/discard_draft"))

        assert first.status_code == status.HTTP_200_OK, first.json()
        assert second.status_code == status.HTTP_200_OK, second.json()
        function = HogFunction.objects.get(id=function_id)
        assert function.draft is None
        assert function.draft_encrypted_inputs is None
        assert function.hog == LIVE_HOG

    def test_staged_secret_survives_a_later_edit_that_resends_the_marker(self):
        function_id = self._create()
        self._stage(function_id, {"inputs": {"url": {"value": "https://example.com/live"}, "token": {"value": "new"}}})

        # The API hands secrets back as `{"secret": true}`; resending that must not revert the staged
        # value to the live one.
        self._stage(
            function_id,
            {"inputs": {"url": {"value": "https://example.com/staged"}, "token": {"secret": True}}},
        )

        function = HogFunction.objects.get(id=function_id)
        assert function.draft_encrypted_inputs["token"]["value"] == "new"
        assert function.encrypted_inputs["token"]["value"] == "live-token"

    def test_publishing_promotes_the_staged_secret(self):
        function_id = self._create()
        self._stage(function_id, {"inputs": {"url": {"value": "https://example.com/live"}, "token": {"value": "new"}}})

        response = self._publish(function_id)

        assert response.status_code == status.HTTP_200_OK, response.json()
        function = HogFunction.objects.get(id=function_id)
        assert function.encrypted_inputs["token"]["value"] == "new"
        assert function.draft_encrypted_inputs is None

    def test_draft_never_carries_secret_values(self):
        function_id = self._create()

        draft = self._stage(
            function_id, {"inputs": {"url": {"value": "https://example.com/live"}, "token": {"value": "new"}}}
        )["draft"]

        assert draft["inputs"]["token"] == {"secret": True}
        stored_draft = HogFunction.objects.get(id=function_id).draft
        assert stored_draft is not None
        assert "token" not in stored_draft["inputs"]


class TestHogFunctionRevisions(DraftTestCase):
    def test_first_live_config_change_also_snapshots_the_outgoing_config(self):
        function_id = self._create()

        self._live_edit(function_id, {"hog": EDITED_HOG})

        revisions = list(self._revisions(function_id).order_by("version"))
        assert [revision.version for revision in revisions] == [1, 2]
        # Rollback to the state before the revision system saw this function must be possible.
        assert revisions[0].content["hog"] == LIVE_HOG
        assert revisions[0].created_by is None
        assert revisions[1].content["hog"] == EDITED_HOG
        assert revisions[1].created_by == self.user

    @parameterized.expand(
        [
            # `to_internal_value` re-injects inputs/filters and the serializer recompiles bytecode on
            # every save, so an unchanged config must still compare equal and stay unversioned.
            ("metadata_only", {"name": "Renamed"}, True),
            ("config_resent_unchanged", {"hog": LIVE_HOG, "name": "Renamed"}, True),
            ("flag_off", {"hog": EDITED_HOG}, False),
        ]
    )
    def test_no_revision_is_written(self, _name: str, payload: dict, flag_on: bool):
        function_id = self._create()

        with patch(FLAG_PATH, return_value=flag_on):
            self._live_edit(function_id, payload)

        assert not self._revisions(function_id).exists()
        assert HogFunction.objects.get(id=function_id).version == 1

    def test_revisions_list_is_newest_first_and_omits_config(self):
        function_id = self._create()
        self._live_edit(function_id, {"hog": EDITED_HOG})

        response = self.client.get(self._url(function_id, "/revisions"))

        assert response.status_code == status.HTTP_200_OK, response.json()
        results = response.json()["results"]
        assert [result["version"] for result in results] == [2, 1]
        assert "content" not in results[0]

    def test_revision_detail_returns_config_without_secret_values(self):
        function_id = self._create()
        self._live_edit(function_id, {"hog": EDITED_HOG})

        response = self.client.get(self._url(function_id, "/revisions/1"))

        assert response.status_code == status.HTTP_200_OK, response.json()
        assert response.json()["content"]["hog"] == LIVE_HOG
        assert "token" not in response.json()["content"]["inputs"]

    def test_unknown_revision_is_a_404(self):
        function_id = self._create()

        response = self.client.get(self._url(function_id, "/revisions/99"))

        assert response.status_code == status.HTTP_404_NOT_FOUND, response.json()

    def test_restore_stages_the_old_config_without_touching_the_live_one(self):
        function_id = self._create()
        self._live_edit(function_id, {"hog": EDITED_HOG})

        response = self.client.post(self._url(function_id, "/revisions/1/restore"))

        assert response.status_code == status.HTTP_200_OK, response.json()
        function = HogFunction.objects.get(id=function_id)
        assert function.draft is not None
        assert function.draft["hog"] == LIVE_HOG
        assert function.hog == EDITED_HOG

    def test_restore_over_an_open_draft_needs_overwrite(self):
        function_id = self._create()
        self._live_edit(function_id, {"hog": EDITED_HOG})
        self._stage(function_id, {"hog": "fetch(inputs.url, {'method': 'PATCH'});"})

        conflict = self.client.post(self._url(function_id, "/revisions/1/restore"))
        forced = self.client.post(self._url(function_id, "/revisions/1/restore"), {"overwrite": True})

        assert conflict.status_code == status.HTTP_409_CONFLICT, conflict.json()
        assert forced.status_code == status.HTTP_200_OK, forced.json()
        restored_draft = HogFunction.objects.get(id=function_id).draft
        assert restored_draft is not None
        assert restored_draft["hog"] == LIVE_HOG

    @parameterized.expand(
        [
            ("publish", "post", "/publish"),
            ("discard_draft", "post", "/discard_draft"),
            ("revisions", "get", "/revisions"),
            ("revision_detail", "get", "/revisions/1"),
            ("restore_revision", "post", "/revisions/1/restore"),
        ]
    )
    def test_endpoints_are_rejected_when_the_flag_is_off(self, _name: str, method: str, suffix: str):
        function_id = self._create()

        with patch(FLAG_PATH, return_value=False):
            response = getattr(self.client, method)(self._url(function_id, suffix))

        assert response.status_code == status.HTTP_400_BAD_REQUEST, response.json()
