from posthog.test.base import APIBaseTest
from unittest.mock import patch

from parameterized import parameterized
from rest_framework import status

from posthog.models.activity_logging.activity_log import ActivityLog

from products.cdp.backend.api.hog_function import HogFunctionViewSet
from products.cdp.backend.models.hog_functions.hog_function import HogFunction
from products.cdp.backend.models.hog_functions.hog_function_revision import HogFunctionRevision

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
            ("desktop_app", "posthog/desktop.hog.dev; version: 1.0"),
            ("mobile_app", "posthog/mobile.hog.dev; version: 1.0"),
        ]
    )
    def test_first_party_app_edit_also_stages_a_draft(self, _name: str, user_agent: str):
        # These reach REST under their own user-agent rather than through the MCP header, so the
        # review gate depends on their membership in AGENT_EVENT_SOURCES. Dropping either would
        # apply an agent's edit straight to a running function with nothing else to signal it.
        function_id = self._create()

        with patch(RELOAD_PATH) as mock_reload:
            response = self.client.patch(
                self._url(function_id), {"hog": EDITED_HOG}, headers={"user-agent": user_agent}
            )

        assert response.status_code == status.HTTP_200_OK, response.json()
        assert response.json()["draft"]["hog"] == EDITED_HOG
        mock_reload.assert_not_called()
        assert HogFunction.objects.get(id=function_id).hog == LIVE_HOG

    @parameterized.expand(
        [
            # An agent can't stage a draft on a function that isn't running, and the web builder
            # saves what the person just reviewed, so neither routes to a draft.
            ("disabled_function", True, {"enabled": False}),
            ("web_caller", False, {}),
            # Only destinations are in the cycle for now. A transformation edit still applies live.
            ("transformation", True, {"type": "transformation", "hog": "return event"}),
        ]
    )
    def test_config_edit_applies_live(self, _name: str, from_agent: bool, overrides: dict):
        function_id = self._create(**overrides)

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

    def test_metadata_in_a_draft_edit_does_not_revert_a_concurrent_live_edit(self):
        function_id = self._create()
        concurrent_hog = "fetch(inputs.url, {'method': 'DELETE'});"
        real_should_route_to_draft = HogFunctionViewSet._should_route_to_draft

        def live_edit_lands_after_initial_fetch(viewset, serializer):
            # Stand in for a builder edit committing between the request's initial unlocked fetch
            # and its write: draft routing resolves after get_object() and before the transaction.
            HogFunction.objects.filter(id=function_id).update(hog=concurrent_hog)
            return real_should_route_to_draft(viewset, serializer)

        with patch.object(HogFunctionViewSet, "_should_route_to_draft", live_edit_lands_after_initial_fetch):
            response = self._agent_patch(function_id, {"name": "Renamed", "hog": EDITED_HOG})

        assert response.status_code == status.HTTP_200_OK, response.json()
        function = HogFunction.objects.get(id=function_id)
        assert function.name == "Renamed"
        # The metadata save must not write the request-start config back over the concurrent edit.
        assert function.hog == concurrent_hog
        assert function.draft is not None
        assert function.draft["hog"] == EDITED_HOG

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

    @parameterized.expand(
        [
            # The draft is a full snapshot, so a token minted before either side moved would publish
            # over whatever landed since. Both cases have to force a fresh preview.
            ("draft_moved", True),
            ("live_moved", False),
        ]
    )
    def test_publish_with_a_token_from_before_the_latest_edit_conflicts(self, _name: str, edit_draft: bool):
        function_id = self._create()
        self._stage(function_id, {"hog": EDITED_HOG})
        stale_token = self._preview_publish(function_id)["confirm_token"]
        if edit_draft:
            self._stage(function_id, {"hog": "fetch(inputs.url, {'method': 'PATCH'});"})
        else:
            self._live_edit(function_id, {"name": "Renamed in the builder"})

        response = self.client.post(self._url(function_id, "/publish"), {"confirm": True, "confirm_token": stale_token})

        assert response.status_code == status.HTTP_409_CONFLICT, response.json()
        assert HogFunction.objects.get(id=function_id).hog == LIVE_HOG

    def test_publishing_a_disabled_function_skips_the_confirm_token(self):
        function_id = self._create()
        self._stage(function_id, {"hog": EDITED_HOG})
        self._live_edit(function_id, {"enabled": False})

        # Nothing is running, so there is no traffic to misroute and no receipt to insist on.
        response = self.client.post(self._url(function_id, "/publish"), {"confirm": True})

        assert response.status_code == status.HTTP_200_OK, response.json()
        assert HogFunction.objects.get(id=function_id).hog == EDITED_HOG

    def test_enabling_with_a_draft_open_is_refused(self):
        function_id = self._create()
        self._stage(function_id, {"hog": EDITED_HOG})
        self._live_edit(function_id, {"enabled": False})

        response = self.client.patch(self._url(function_id), {"enabled": True})

        assert response.status_code == status.HTTP_400_BAD_REQUEST, response.json()
        assert HogFunction.objects.get(id=function_id).enabled is False

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
        # The no-op second discard must not add audit noise.
        assert (
            ActivityLog.objects.filter(scope="HogFunction", item_id=function_id, activity="draft_discarded").count()
            == 1
        )

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

    def test_enabling_with_a_draft_open_is_refused_for_coercible_booleans(self):
        function_id = self._create()
        self._stage(function_id, {"hog": EDITED_HOG})
        self._live_edit(function_id, {"enabled": False})

        # BooleanField coerces "true" to True, so the refusal must fire on the validated value, not
        # the raw payload.
        response = self.client.patch(self._url(function_id), {"enabled": "true"})

        assert response.status_code == status.HTTP_400_BAD_REQUEST, response.json()
        assert HogFunction.objects.get(id=function_id).enabled is False

    @parameterized.expand(
        [
            # A draft edit races other draft edits, a live edit races the live row; either way a
            # base_updated_at older than the stored side means someone wrote in between.
            ("draft_edit", True),
            ("live_edit", False),
        ]
    )
    def test_stale_base_updated_at_is_a_conflict(self, _name: str, agent_edit: bool):
        function_id = self._create()
        self._stage(function_id, {"hog": EDITED_HOG})

        payload = {"hog": "fetch(inputs.url, {'method': 'PATCH'});", "base_updated_at": "2020-01-01T00:00:00Z"}
        response = (
            self._agent_patch(function_id, payload)
            if agent_edit
            else self.client.patch(self._url(function_id), payload)
        )

        assert response.status_code == status.HTTP_409_CONFLICT, response.json()

    def test_current_base_updated_at_is_accepted(self):
        function_id = self._create()
        staged = self._stage(function_id, {"hog": EDITED_HOG})

        response = self._agent_patch(
            function_id,
            {"hog": "fetch(inputs.url, {'method': 'PATCH'});", "base_updated_at": staged["draft_updated_at"]},
        )

        assert response.status_code == status.HTTP_200_OK, response.json()

    def _test_invoke(self, function_id: str, payload: dict):
        with patch("products.cdp.backend.api.hog_function.create_hog_invocation_test") as mock_invoke:
            mock_invoke.return_value.status_code = 200
            mock_invoke.return_value.json.return_value = {"status": "success", "logs": []}
            response = self.client.post(self._url(function_id, "/invocations"), payload)
        return response, mock_invoke

    def test_invocations_use_draft_tests_staged_config_and_secrets(self):
        function_id = self._create()
        self._stage(
            function_id,
            {"hog": EDITED_HOG, "inputs": {"url": {"value": "https://example.com/live"}, "token": {"value": "new"}}},
        )

        response, mock_invoke = self._test_invoke(function_id, {"use_draft": True})

        assert response.status_code == status.HTTP_200_OK, response.json()
        configuration = mock_invoke.call_args.kwargs["payload"]["configuration"]
        assert configuration["hog"] == EDITED_HOG
        # The staged secret is what gets exercised, not the live one it will replace.
        assert configuration["inputs"]["token"]["value"] == "new"

    def test_invocations_use_draft_recovers_unstaged_secrets_from_live(self):
        function_id = self._create()
        self._stage(function_id, {"hog": EDITED_HOG})

        response, mock_invoke = self._test_invoke(function_id, {"use_draft": True})

        assert response.status_code == status.HTTP_200_OK, response.json()
        configuration = mock_invoke.call_args.kwargs["payload"]["configuration"]
        assert configuration["inputs"]["token"]["value"] == "live-token"

    def test_invocations_use_draft_without_a_draft_is_rejected(self):
        function_id = self._create()

        response = self.client.post(self._url(function_id, "/invocations"), {"use_draft": True})

        assert response.status_code == status.HTTP_400_BAD_REQUEST, response.json()

    @parameterized.expand(
        [
            # Only the destination type is held to the create-disabled-then-enable path: the alert
            # recipe legitimately creates internal_destination functions enabled in one call, and the
            # web builder is a human clicking through a confirm UI.
            ("agent_destination", True, "destination", status.HTTP_400_BAD_REQUEST),
            ("agent_internal_destination", True, "internal_destination", status.HTTP_201_CREATED),
            ("web_destination", False, "destination", status.HTTP_201_CREATED),
        ]
    )
    def test_create_as_enabled(self, _name: str, from_agent: bool, function_type: str, expected: int):
        payload = {**BASE_FUNCTION, "type": function_type}
        headers = {"x-posthog-client": "mcp"} if from_agent else {}

        response = self.client.post(self._url(), data=payload, headers=headers)

        assert response.status_code == expected, response.json()


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
            ("metadata_only", {"name": "Renamed"}),
            ("config_resent_unchanged", {"hog": LIVE_HOG, "name": "Renamed"}),
        ]
    )
    def test_no_revision_is_written(self, _name: str, payload: dict):
        function_id = self._create()

        self._live_edit(function_id, payload)

        assert not self._revisions(function_id).exists()
        assert HogFunction.objects.get(id=function_id).version == 1

    def test_recompiled_filter_bytecode_does_not_create_a_revision(self):
        function_id = self._create()
        # Stand in for a background re-save that recompiled filter bytecode without the config
        # changing, which is what refresh_affected_hog_functions does after an action or cohort edit.
        # queryset.update() so no signal or serializer runs.
        HogFunction.objects.filter(id=function_id).update(filters={"source": "events", "bytecode": ["_H", 1, 999]})

        self._live_edit(function_id, {"name": "Renamed"})

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
