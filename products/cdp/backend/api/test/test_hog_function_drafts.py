from typing import Any

from posthog.test.base import APIBaseTest
from unittest.mock import patch

from django.test import SimpleTestCase

from parameterized import parameterized
from rest_framework import status

from posthog.models import PersonalAPIKey
from posthog.models.activity_logging.activity_log import ActivityLog
from posthog.models.utils import generate_random_token_personal, hash_key_value

from products.cdp.backend.api.hog_function import HogFunctionViewSet, supplied_input_keys
from products.cdp.backend.api.test.secret_sender import (
    MOVED_SENDER_HOG,
    MOVED_URL,
    SENDER_HOG,
    SENDER_URL,
    counted_reentries,
    secret_host_binding_flag,
    sender_inputs,
)
from products.cdp.backend.models.hog_functions.hog_function import HogFunction
from products.cdp.backend.models.hog_functions.hog_function_revision import HogFunctionRevision
from products.cdp.backend.templates.helpers import mock_transpile
from products.cdp.backend.validation import MASKED_SECRET_VALUE

RELOAD_PATH = "products.cdp.backend.models.hog_functions.hog_function.reload_hog_functions_on_workers"

LIVE_HOG = "fetch(inputs.url);"
EDITED_HOG = "fetch(inputs.url, {'method': 'PUT'});"

BASE_FUNCTION: dict[str, Any] = {
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


class TestSuppliedInputKeys(SimpleTestCase):
    @parameterized.expand(
        [
            ("masked_string", {"secret": True, "value": MASKED_SECRET_VALUE}, False),
            ("masked_dictionary", {"secret": True, "value": {"Authorization": MASKED_SECRET_VALUE}}, False),
            (
                "partly_masked_dictionary",
                {"secret": True, "value": {"Authorization": MASKED_SECRET_VALUE, "X-New": "typed"}},
                True,
            ),
            ("typed_string", {"value": "typed"}, True),
        ]
    )
    def test_an_echoed_mask_does_not_replace_a_stored_secret(self, _name: str, item: dict, supplied: bool) -> None:
        assert supplied_input_keys({"token": item}) == ({"token"} if supplied else set())


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

        self._stage(
            function_id,
            {
                "name": "Renamed",
                "enabled": False,
                "filters": {"source": "events"},
                "inputs": {"url": {"value": "https://example.com/live"}, "token": {"value": "rotated-token"}},
            },
        )

        function = HogFunction.objects.get(id=function_id)
        assert function.name == "Renamed"
        assert function.enabled is False
        assert function.draft is not None
        assert function.draft["filters"]["source"] == "events"
        assert function.encrypted_inputs["token"]["value"] == "live-token"
        assert function.draft_encrypted_inputs["token"]["value"] == "rotated-token"

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

    @parameterized.expand(
        [
            (
                "unmarked",
                {"value": {"Authorization": "********", "X-New": "typed"}},
                {"Authorization": "staged", "X-New": "typed"},
            ),
            (
                "marked_as_read",
                {"secret": True, "value": {"Authorization": "********", "X-New": "typed"}},
                {"Authorization": "staged", "X-New": "typed"},
            ),
            ("emptied", {"secret": True, "value": {}}, {}),
        ]
    )
    def test_a_later_draft_edit_to_a_staged_dictionary_secret(self, _name: str, sent: dict, expected: dict):
        function_id = self._create(
            inputs_schema=[
                BASE_FUNCTION["inputs_schema"][0],
                {"key": "secret_headers", "type": "dictionary", "label": "Secret headers", "secret": True},
            ],
            inputs={
                "url": {"value": "https://example.com/live"},
                "secret_headers": {"value": {"Authorization": "live"}},
            },
        )
        url = {"value": "https://example.com/live"}
        self._stage(function_id, {"inputs": {"url": url, "secret_headers": {"value": {"Authorization": "staged"}}}})

        self._stage(function_id, {"inputs": {"url": url, "secret_headers": sent}})

        staged = HogFunction.objects.get(id=function_id).draft_encrypted_inputs["secret_headers"]["value"]
        assert staged == expected

    @parameterized.expand(
        [
            ("changes_the_url", [{"inputs": sender_inputs(MOVED_URL)}], {"staged": 1}, status.HTTP_400_BAD_REQUEST),
            (
                "enters_the_secret_with_the_change",
                [{"inputs": sender_inputs(MOVED_URL, {"value": "new"})}],
                {"reentered": 1},
                status.HTTP_200_OK,
            ),
            (
                "enters_the_secret_after_staging_code",
                [{"hog": MOVED_SENDER_HOG}, {"inputs": sender_inputs(SENDER_URL, {"value": "new"})}],
                {"staged": 1, "reentered": 1},
                status.HTTP_200_OK,
            ),
        ]
    )
    def test_draft_that_changes_a_legacy_function_needs_the_secret_to_test_or_publish(
        self, _name: str, edits: list[dict], expected_staged_outcomes: dict[str, int], expected_status: int
    ):
        function_id = self._create(hog=SENDER_HOG, inputs={"url": {"value": SENDER_URL}, "token": {"value": "live"}})

        with secret_host_binding_flag(True):
            with counted_reentries("draft") as staged_outcomes:
                for edit in edits:
                    self._stage(function_id, edit)
            tested, mock_invoke = self._test_invoke(function_id, {"use_draft": True, "mock_async_functions": False})
            published = self._publish(function_id)

        assert (tested.status_code, published.status_code) == (expected_status, expected_status), published.json()
        assert mock_invoke.called == (expected_status == status.HTTP_200_OK)
        assert staged_outcomes == expected_staged_outcomes
        live_token = HogFunction.objects.get(id=function_id).encrypted_inputs["token"]["value"]
        assert live_token == ("live" if expected_status == status.HTTP_400_BAD_REQUEST else "new")

    @parameterized.expand(
        [
            (
                "by_adding_an_entry",
                {
                    "url": {"value": MOVED_URL},
                    "secret_headers": {"value": {"url": SENDER_URL, "token": "********", "X-Extra": "1"}},
                },
            ),
            (
                "by_editing_its_own_url_entry",
                {"url": {"value": SENDER_URL}, "secret_headers": {"value": {"url": MOVED_URL, "token": "********"}}},
            ),
        ]
    )
    def test_draft_that_keeps_part_of_a_dictionary_secret_cannot_be_published(self, _name: str, staged_inputs: dict):
        function_id = self._create(
            hog="fetch(inputs.secret_headers.url ?? inputs.url, {'headers': inputs.secret_headers});",
            inputs_schema=[
                BASE_FUNCTION["inputs_schema"][0],
                {"key": "secret_headers", "type": "dictionary", "label": "Secret headers", "secret": True},
            ],
            inputs={"url": {"value": SENDER_URL}, "secret_headers": {"value": {"url": SENDER_URL, "token": "live"}}},
        )

        with secret_host_binding_flag(True):
            self._stage(function_id, {"inputs": staged_inputs})
            published = self._publish(function_id)

        assert published.status_code == status.HTTP_400_BAD_REQUEST, published.json()
        assert HogFunction.objects.get(id=function_id).encrypted_inputs["secret_headers"]["value"]["token"] == "live"

    @parameterized.expand(
        [
            ("stored_secret", "destination", SENDER_HOG, {"secret": True}, "secret", status.HTTP_400_BAD_REQUEST),
            (
                "entered_secret",
                "destination",
                SENDER_HOG,
                {"value": "typed for this test"},
                "secret",
                status.HTTP_200_OK,
            ),
            # A transformation is under the enabled-functions cap, which validates the nested
            # configuration through a branch of its own.
            (
                "stored_secret_printed_by_a_transformation",
                "transformation",
                "print(inputs.token); return event",
                {"secret": True},
                "secret",
                status.HTTP_400_BAD_REQUEST,
            ),
            (
                "stored_secret_left_out_of_the_schema",
                "destination",
                SENDER_HOG,
                None,
                "omitted",
                status.HTTP_400_BAD_REQUEST,
            ),
            ("stored_secret_declared_public", "destination", SENDER_HOG, None, "public", status.HTTP_400_BAD_REQUEST),
            (
                "plaintext_secret_declared_public",
                "destination",
                MOVED_SENDER_HOG,
                None,
                "public",
                status.HTTP_400_BAD_REQUEST,
                True,
            ),
        ]
    )
    def test_test_invocation_that_changes_a_legacy_function_needs_the_secret(
        self,
        _name: str,
        function_type: str,
        tested_hog: str,
        token: dict | None,
        token_schema: str,
        expected_status: int,
        stored_in_plaintext: bool = False,
    ):
        stored_hog = SENDER_HOG if function_type == "destination" else "return event"
        stored_inputs = {"url": {"value": SENDER_URL}, "token": {"value": "live"}}
        function_id = self._create(type=function_type, hog=stored_hog, inputs=stored_inputs)
        if stored_in_plaintext:
            HogFunction.objects.filter(id=function_id).update(inputs=stored_inputs, encrypted_inputs=None)
        url_schema, secret_token_schema = BASE_FUNCTION["inputs_schema"]
        tested_schemas = {
            "secret": [url_schema, secret_token_schema],
            "omitted": [url_schema],
            "public": [url_schema, {**secret_token_schema, "secret": False}],
        }
        configuration = {
            **BASE_FUNCTION,
            "type": function_type,
            "hog": tested_hog,
            "inputs_schema": tested_schemas[token_schema],
            "inputs": {"url": {"value": MOVED_URL}, **({"token": token} if token else {})},
        }
        if stored_in_plaintext:
            # The serializer fills omitted inputs from the stored function, plaintext secret included.
            del configuration["inputs"]

        with secret_host_binding_flag(True):
            response, mock_invoke = self._test_invoke(
                function_id, {"configuration": configuration, "mock_async_functions": False}
            )

        assert response.status_code == expected_status, response.json()
        assert mock_invoke.called == (expected_status == status.HTTP_200_OK)
        if mock_invoke.called:
            assert token is not None
            sent_secrets = mock_invoke.call_args.kwargs["payload"]["configuration"]["encrypted_inputs"]
            assert {key: item["value"] for key, item in sent_secrets.items()} == {"token": token["value"]}

    def test_publish_resolves_the_rollout_flag_before_locking_the_row(self):
        function_id = self._create(hog=SENDER_HOG, inputs={"url": {"value": SENDER_URL}, "token": {"value": "live"}})
        self._stage(function_id, {"hog": MOVED_SENDER_HOG})
        locked_at_lookup: list[bool] = []
        real_select_for_update = HogFunction.objects.select_for_update
        locks: list[str] = []

        def lock(*args, **kwargs):
            locks.append("locked")
            return real_select_for_update(*args, **kwargs)

        def flag(*args, **kwargs) -> bool:
            locked_at_lookup.append(bool(locks))
            return True

        with (
            patch("products.cdp.backend.api.hog_function.posthoganalytics.feature_enabled", side_effect=flag),
            patch.object(HogFunction.objects, "select_for_update", side_effect=lock),
        ):
            published = self._publish(function_id)

        assert published.status_code == status.HTTP_400_BAD_REQUEST, published.json()
        assert locked_at_lookup == [False]

    @parameterized.expand(
        [
            ("boolean_to_number", "json", True, "json", 1, status.HTTP_400_BAD_REQUEST),
            ("unchanged", "json", True, "json", True, status.HTTP_200_OK),
            ("string_turned_into_a_boolean", "string", "1", "boolean", "1", status.HTTP_400_BAD_REQUEST),
        ]
    )
    def test_input_type_or_value_change_asks_for_the_secret(
        self, _name: str, stored_type: str, stored: Any, new_type: str, new: Any, expected_status: int
    ):
        target_schema = {"key": "target", "type": stored_type, "label": "Target", "required": True}
        schemas = [*BASE_FUNCTION["inputs_schema"], target_schema]
        function_id = self._create(
            hog="fetch(concat('https://', inputs.target, '.example.com/'), {'headers': {'Authorization': inputs.token}});",
            inputs_schema=schemas,
            inputs={**sender_inputs(SENDER_URL, {"value": "live"}), "target": {"value": stored}},
        )

        with secret_host_binding_flag(True):
            response = self.client.patch(
                self._url(function_id),
                {
                    "inputs_schema": [*BASE_FUNCTION["inputs_schema"], {**target_schema, "type": new_type}],
                    "inputs": {**sender_inputs(SENDER_URL), "target": {"value": new}},
                },
            )

        assert response.status_code == expected_status, response.json()

    @parameterized.expand([("same_order", False, status.HTTP_200_OK), ("reordered", True, status.HTTP_400_BAD_REQUEST)])
    def test_test_invocation_that_reorders_a_dictionary_input_needs_the_secret(
        self, _name: str, reorder: bool, expected_status: int
    ):
        targets_schema = {"key": "targets", "type": "dictionary", "label": "Targets"}
        function_id = self._create(
            hog="fetch(values(inputs.targets)[1], {'headers': {'Authorization': inputs.token}});",
            inputs_schema=[*BASE_FUNCTION["inputs_schema"], targets_schema],
            inputs={
                **sender_inputs(SENDER_URL, {"value": "live"}),
                "targets": {"value": {"a": "https://hooks.example.com", "b": MOVED_URL}},
            },
        )
        # The test sends back the function as the API returns it, as the editor does.
        configuration = self.client.get(self._url(function_id)).json()
        targets = configuration["inputs"]["targets"]["value"]
        if reorder:
            configuration["inputs"]["targets"]["value"] = dict(reversed(targets.items()))

        with secret_host_binding_flag(True):
            response, _ = self._test_invoke(function_id, {"configuration": configuration})

        assert response.status_code == expected_status, response.json()

    @parameterized.expand(
        [
            ("declared_public", True, None, status.HTTP_400_BAD_REQUEST),
            ("dropped_from_the_schema", False, None, status.HTTP_400_BAD_REQUEST),
            ("declared_public_with_a_typed_value", True, {"value": "typed"}, status.HTTP_200_OK),
        ]
    )
    def test_live_edit_that_unsecrets_a_stored_secret_needs_a_new_value(
        self, _name: str, keep_schema_entry: bool, token: dict | None, expected_status: int
    ):
        url_schema, token_schema = BASE_FUNCTION["inputs_schema"]
        function_id = self._create(hog=SENDER_HOG, inputs=sender_inputs(SENDER_URL, {"value": "live"}))
        schemas = [url_schema, *([{**token_schema, "secret": False}] if keep_schema_entry else [])]
        change: dict[str, Any] = {"hog": MOVED_SENDER_HOG, "inputs_schema": schemas}
        if token is not None:
            change["inputs"] = {"url": {"value": SENDER_URL}, "token": token}

        with secret_host_binding_flag(True):
            response = self.client.patch(self._url(function_id), change)

        assert response.status_code == expected_status, response.json()

    def test_entering_one_secret_needs_its_legacy_siblings_entered_too(self):
        sibling_schema = {"key": "target", "type": "string", "label": "Target", "secret": True}
        function_id = self._create(
            hog="fetch(inputs.target, {'headers': {'Authorization': inputs.token}});",
            inputs_schema=[*BASE_FUNCTION["inputs_schema"], sibling_schema],
            inputs={**sender_inputs(SENDER_URL, {"value": "live"}), "target": {"value": SENDER_URL}},
        )

        with secret_host_binding_flag(True):
            response = self.client.patch(
                self._url(function_id),
                {"inputs": {**sender_inputs(SENDER_URL), "target": {"value": MOVED_URL}}},
            )

        assert response.status_code == status.HTTP_400_BAD_REQUEST, response.json()
        assert (response.json()["attr"], response.json()["code"]) == ("inputs__token", "secret_reentry_required")

    def test_draft_never_carries_secret_values(self):
        function_id = self._create()

        draft = self._stage(
            function_id, {"inputs": {"url": {"value": "https://example.com/live"}, "token": {"value": "new"}}}
        )["draft"]

        assert draft["inputs"]["token"] == {"secret": True}
        stored_draft = HogFunction.objects.get(id=function_id).draft
        assert stored_draft is not None
        assert "token" not in stored_draft["inputs"]

    @parameterized.expand([("inputs",), ("mappings",)])
    def test_input_values_are_masked_in_activity_logs(self, field: str) -> None:
        function_id = self._create(enabled=False)
        payload = (
            {"inputs": {"url": {"value": "https://example.com/private-input"}, "token": {"secret": True}}}
            if field == "inputs"
            else {
                "mappings": [
                    {
                        "inputs_schema": [{"key": "message", "type": "string"}],
                        "inputs": {"message": {"value": "example-private-input"}},
                    }
                ]
            }
        )

        self._live_edit(function_id, payload)

        logs = ActivityLog.objects.filter(
            team_id=self.team.id, scope="HogFunction", item_id=function_id, activity="updated"
        )
        changes = [
            change
            for log in logs
            for change in (log.detail["changes"] if log.detail else [])
            if change["field"] == field
        ]
        assert changes
        if field == "inputs":
            assert all(change["after"]["url"] == "changed" for change in changes)
            assert all(set(change["after"].values()) <= {"masked", "changed"} for change in changes)
        else:
            assert all(change["after"] == "masked" for change in changes)
        assert all("private-input" not in str(log.detail) for log in logs)

    @patch("products.cdp.backend.site_functions.transpile", side_effect=mock_transpile)
    def test_site_function_transpiled_output_is_not_written_to_activity_logs(self, _mock_transpile) -> None:
        function_id = self._create(
            type="site_destination",
            hog="export function onEvent() {}",
            inputs_schema=[{"key": "url", "type": "string", "label": "Webhook URL", "required": True}],
            inputs={"url": {"value": "https://example.com/private-input"}},
        )

        self._live_edit(function_id, {"hog": "export function onEvent() { return 1; }"})

        logs = ActivityLog.objects.filter(
            team_id=self.team.id, scope="HogFunction", item_id=function_id, activity="updated"
        )
        changed_fields = {change["field"] for log in logs for change in (log.detail["changes"] if log.detail else [])}
        assert "hog" in changed_fields
        assert "transpiled" not in changed_fields
        assert all("private-input" not in str(log.detail) for log in logs)

    @parameterized.expand(
        [
            ("live_secret_last", False, [False, True]),
            ("live_secret_first", False, [True, False]),
            ("draft_secret_last", True, [False, True]),
            ("draft_secret_first", True, [True, False]),
            ("enabled_raw_api_secret_last", True, [False, True], False),
            ("enabled_raw_api_secret_first", True, [True, False], False),
        ]
    )
    def test_duplicate_input_keys_are_rejected(
        self, _name: str, enabled: bool, secret_flags: list[bool], from_agent: bool = True
    ) -> None:
        function_id = self._create(enabled=enabled)
        function = HogFunction.objects.get(id=function_id)
        saved_inputs = function.inputs
        saved_secrets = function.encrypted_inputs
        revision_count = self._revisions(function_id).count()
        logs = ActivityLog.objects.filter(team_id=self.team.id, scope="HogFunction", item_id=function_id)
        log_count = logs.count()

        payload = {
            "inputs_schema": [
                BASE_FUNCTION["inputs_schema"][0],
                *[{"key": "token", "type": "string", "secret": secret} for secret in secret_flags],
            ]
        }
        response = (
            self._agent_patch(function_id, payload)
            if from_agent
            else self.client.patch(self._url(function_id), payload)
        )

        assert response.status_code == status.HTTP_400_BAD_REQUEST, response.json()
        assert response.json()["attr"] == "inputs_schema"
        function.refresh_from_db()
        assert function.inputs == saved_inputs
        assert function.encrypted_inputs == saved_secrets
        assert function.draft is None
        assert self._revisions(function_id).count() == revision_count
        assert logs.count() == log_count
        assert all("live-token" not in str(log.detail) for log in logs)
        response = self.client.get(self._url(function_id))
        assert response.status_code == status.HTTP_200_OK
        assert response.json()["inputs"]["token"] == {"secret": True}
        assert "live-token" not in response.content.decode()

    @parameterized.expand(
        [
            ("live_mask", False, {"secret": True}),
            ("draft_mask", True, {"secret": True}),
            ("draft_display_mask", True, {"secret": True, "value": "********"}),
            ("draft_empty", True, {}),
            ("draft_new_value", True, {"value": "example-mapping-token"}),
            ("draft_schema_only", True, None),
        ]
    )
    def test_mapping_secret_inputs_are_rejected(self, _name: str, enabled: bool, input_value: dict | None) -> None:
        function_id = self._create(enabled=enabled)
        if enabled:
            self._stage(
                function_id,
                {
                    "inputs": {
                        "url": {"value": "https://example.com/live"},
                        "token": {"value": "example-staged-token"},
                    }
                },
            )
        function = HogFunction.objects.get(id=function_id)
        saved_draft = function.draft
        saved_secrets = function.encrypted_inputs
        saved_draft_secrets = function.draft_encrypted_inputs
        revision_count = self._revisions(function_id).count()
        mapping: dict[str, Any] = {
            "inputs_schema": [{"key": "token", "type": "string", "secret": True}],
        }
        if input_value is not None:
            mapping["inputs"] = {"token": input_value}

        response = self._agent_patch(function_id, {"mappings": [mapping]})

        assert response.status_code == status.HTTP_400_BAD_REQUEST, response.json()
        assert response.json()["attr"] == "mappings__0__inputs_schema"
        function.refresh_from_db()
        assert function.mappings is None
        assert function.draft == saved_draft
        assert function.encrypted_inputs == saved_secrets
        assert function.draft_encrypted_inputs == saved_draft_secrets
        assert self._revisions(function_id).count() == revision_count
        response = self.client.get(self._url(function_id))
        assert response.status_code == status.HTTP_200_OK
        assert response.json()["inputs"]["token"] == {"secret": True}
        for secret in ("live-token", "example-staged-token", "example-mapping-token"):
            assert secret not in response.content.decode()
            assert not self._revisions(function_id).filter(content__icontains=secret).exists()

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
        assert configuration["encrypted_inputs"]["token"]["value"] == "new"

    def test_invocations_use_draft_recovers_unstaged_secrets_from_live(self):
        function_id = self._create()
        self._stage(function_id, {"hog": EDITED_HOG})

        response, mock_invoke = self._test_invoke(function_id, {"use_draft": True})

        assert response.status_code == status.HTTP_200_OK, response.json()
        configuration = mock_invoke.call_args.kwargs["payload"]["configuration"]
        assert configuration["inputs"]["token"]["value"] == "live-token"
        assert configuration["encrypted_inputs"]["token"]["value"] == "live-token"

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
        payload: dict[str, Any] = {**BASE_FUNCTION, "type": function_type}
        if function_type == "internal_destination":
            # Internal destinations have to name the event they subscribe to.
            payload["filters"] = {"events": [{"id": "$activity_log_entry_created", "type": "events"}]}
        headers = {"x-posthog-client": "mcp"} if from_agent else {}

        response = self.client.post(self._url(), data=payload, headers=headers)

        assert response.status_code == expected, response.json()


class TestHogFunctionRevisions(DraftTestCase):
    @parameterized.expand([("secret_first", True), ("secret_last", False)])
    def test_legacy_mapping_secrets_are_masked_on_reads(self, _name: str, secret_first: bool) -> None:
        function_id = self._create()
        schemas = [
            {"key": "credential", "type": "string", "secret": True, "default": "example-private-default"},
            {"key": "credential", "type": "string", "default": "example-private-default"},
        ]
        if not secret_first:
            schemas.reverse()
        mappings = [
            {
                "name": "Page view",
                "inputs_schema": schemas,
                "inputs": {
                    "credential": {"value": "example-private-value", "bytecode": ["example-private-value"]},
                    "event_name": {"value": "page_view"},
                },
            }
        ]
        content = {"inputs_schema": [], "inputs": {}, "mappings": mappings}
        HogFunction.objects.filter(id=function_id).update(mappings=mappings, draft=content)
        function = HogFunction.objects.get(id=function_id)
        self._revisions(function_id).filter(version=1).update(content=content)

        for suffix in ("", "/revisions/1"):
            response = self.client.get(self._url(function_id, suffix))
            assert response.status_code == status.HTTP_200_OK, response.json()
            assert "example-private" not in response.content.decode()
            data = response.json().get("content", response.json())
            assert data["mappings"][0]["inputs"]["credential"] == {"secret": True}
            assert data["mappings"][0]["inputs"]["event_name"] == {"value": "page_view"}
        response = self.client.get(self._url(), {"full": "true"})
        assert response.status_code == status.HTTP_200_OK
        assert "example-private" not in response.content.decode()
        function.refresh_from_db()
        assert function.mappings == mappings
        assert function.draft == content
        assert self._revisions(function_id).get(version=1).content == content

    @parameterized.expand([("created_with_a_revision", False), ("created_before_creation_revisions", True)])
    def test_first_live_config_change_keeps_the_outgoing_config(self, _name: str, legacy: bool):
        function_id = self._create()
        if legacy:
            self._revisions(function_id).delete()

        self._live_edit(function_id, {"hog": EDITED_HOG})

        revisions = list(self._revisions(function_id).select_related("created_by").order_by("version"))
        assert [revision.version for revision in revisions] == [1, 2]
        # Rollback to the state before the revision system saw this function must be possible.
        assert revisions[0].content["hog"] == LIVE_HOG
        assert revisions[0].created_by == (None if legacy else self.user)
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

        assert list(self._revisions(function_id).values_list("version", flat=True)) == [1]
        assert HogFunction.objects.get(id=function_id).version == 1

    def test_recompiled_filter_bytecode_does_not_create_a_revision(self):
        function_id = self._create()
        # Stand in for a background re-save that recompiled filter bytecode without the config
        # changing, which is what refresh_affected_hog_functions does after an action or cohort edit.
        # queryset.update() so no signal or serializer runs.
        HogFunction.objects.filter(id=function_id).update(filters={"source": "events", "bytecode": ["_H", 1, 999]})

        self._live_edit(function_id, {"name": "Renamed"})

        assert list(self._revisions(function_id).values_list("version", flat=True)) == [1]
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

    @parameterized.expand(
        [
            ("deleted_with_a_session", True, None, status.HTTP_200_OK),
            ("deleted_with_a_read_only_key", True, ["hog_function:read"], status.HTTP_403_FORBIDDEN),
            ("live_with_a_read_only_key", False, ["hog_function:read"], status.HTTP_200_OK),
        ]
    )
    def test_deleted_function_history_needs_write_access(
        self, _name: str, deleted: bool, key_scopes: list[str] | None, expected_status: int
    ):
        function_id = self._create()
        if deleted:
            self._live_edit(function_id, {"deleted": True})
        headers = {}
        if key_scopes is not None:
            key_value = generate_random_token_personal()
            PersonalAPIKey.objects.create(
                label="Read only", user=self.user, secure_value=hash_key_value(key_value), scopes=key_scopes
            )
            self.client.logout()
            headers = {"authorization": f"Bearer {key_value}"}

        listed = self.client.get(self._url(function_id, "/revisions"), headers=headers)
        detail = self.client.get(self._url(function_id, "/revisions/1"), headers=headers)

        assert (listed.status_code, detail.status_code) == (expected_status, expected_status)
        if expected_status == status.HTTP_200_OK:
            assert [result["version"] for result in listed.json()["results"]] == [1]
            assert detail.json()["content"]["hog"] == LIVE_HOG
        if deleted and key_scopes is None:
            listed_ids = [function["id"] for function in self.client.get(self._url()).json()["results"]]
            assert function_id not in listed_ids

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
