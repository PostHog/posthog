from copy import deepcopy
from typing import Any

from unittest.mock import patch

from parameterized import parameterized
from rest_framework import status

from products.cdp.backend.models.hog_functions.hog_function import HogFunction
from products.messaging.backend.unlayer import UnlayerNotConfiguredError, UnlayerRenderError

from .test_hog_function_drafts import BASE_FUNCTION, FLAG_PATH, RELOAD_PATH, DraftTestCase

RENDER_PATH = "products.cdp.backend.api.hog_function.render_design_html"

DESIGN = {
    "body": {
        "id": "body1",
        "rows": [
            {
                "id": "row1",
                "columns": [
                    {
                        "id": "col1",
                        "contents": [{"id": "txt1", "type": "text", "values": {"text": "<p>Old copy</p>"}}],
                    }
                ],
            }
        ],
    }
}

EMAIL_VALUE = {
    "from": "noreply@posthog.com",
    "to": "{person.properties.email}",
    "subject": "Welcome!",
    "preheader": "Fresh off the press",
    "text": "Welcome aboard",
    "html": "<p>Old copy</p>",
    "design": DESIGN,
}

EMAIL_FUNCTION: dict[str, Any] = {
    "name": "Email destination",
    "type": "destination",
    "hog": "return event",
    "enabled": True,
    "inputs_schema": [
        {"key": "email", "type": "native_email", "label": "Email", "required": True},
        {"key": "api_key", "type": "string", "label": "API key", "secret": True, "required": False},
    ],
    "inputs": {"email": {"value": EMAIL_VALUE}, "api_key": {"value": "live-secret"}},
}


class TestHogFunctionEmail(DraftTestCase):
    def _create_email_function(self, **overrides) -> str:
        return self._create(**{**EMAIL_FUNCTION, **overrides})

    def _email_url(self, function_id: str) -> str:
        return self._url(function_id, "/email")

    def _get_email(self, function_id: str):
        return self.client.get(self._email_url(function_id))

    def _patch_email(self, function_id: str, payload: dict):
        return self.client.patch(self._email_url(function_id), payload)

    def _agent_patch_email(self, function_id: str, payload: dict):
        return self.client.patch(self._email_url(function_id), payload, headers={"x-posthog-client": "mcp"})

    def _stored_email_value(self, function_id: str) -> dict:
        inputs = HogFunction.objects.get(id=function_id).inputs
        assert inputs is not None
        return inputs["email"]["value"]

    def _staged_email_value(self, function_id: str) -> dict:
        draft = HogFunction.objects.get(id=function_id).draft
        assert draft is not None
        return draft["inputs"]["email"]["value"]

    # --- GET ---

    def test_get_email_returns_live_value_excluding_html(self):
        function_id = self._create_email_function()

        response = self._get_email(function_id)

        assert response.status_code == status.HTTP_200_OK, response.json()
        body = response.json()
        assert body["subject"] == "Welcome!"
        assert body["from"] == "noreply@posthog.com"
        assert body["to"] == "{person.properties.email}"
        assert body["design"] == DESIGN
        assert body["has_draft"] is False
        # html is derived from design and can be huge - never returned on the read-back.
        assert "html" not in body

    def test_get_email_returns_draft_value_when_one_is_staged(self):
        function_id = self._create_email_function()
        response = self._agent_patch_email(function_id, {"email_patch": {"subject": "Staged subject"}})
        assert response.status_code == status.HTTP_200_OK, response.json()

        body = self._get_email(function_id).json()

        assert body["has_draft"] is True
        assert body["subject"] == "Staged subject"
        # Live stays what a human last approved.
        assert self._stored_email_value(function_id)["subject"] == "Welcome!"

    def test_get_email_on_non_email_function_rejected(self):
        function_id = self._create(**BASE_FUNCTION)

        response = self._get_email(function_id)

        assert response.status_code == status.HTTP_400_BAD_REQUEST

    # --- PATCH: apply + render ---

    @patch(RENDER_PATH, return_value="<p>Rendered</p>")
    def test_design_op_updates_block_and_rerenders_html(self, mock_render):
        function_id = self._create_email_function()

        response = self._patch_email(
            function_id,
            {"operations": [{"op": "update_content", "id": "txt1", "patch": {"values": {"text": "<p>New copy</p>"}}}]},
        )

        assert response.status_code == status.HTTP_200_OK, response.json()
        mock_render.assert_called_once()
        value = self._stored_email_value(function_id)
        assert value["design"]["body"]["rows"][0]["columns"][0]["contents"][0]["values"]["text"] == "<p>New copy</p>"
        assert value["html"] == "<p>Rendered</p>"
        assert response.json()["draft"] is None

    @patch(RENDER_PATH, return_value="<p>Rendered</p>")
    def test_email_patch_merges_fields_without_rerendering(self, mock_render):
        function_id = self._create_email_function()

        response = self._patch_email(function_id, {"email_patch": {"subject": "New subject", "preheader": None}})

        assert response.status_code == status.HTTP_200_OK, response.json()
        mock_render.assert_not_called()
        value = self._stored_email_value(function_id)
        assert value["subject"] == "New subject"
        # A null leaf deletes the key.
        assert "preheader" not in value
        # Untouched fields survive the merge.
        assert value["text"] == "Welcome aboard"
        assert value["html"] == "<p>Old copy</p>"

    # --- PATCH: validation ---

    @parameterized.expand(
        [
            ("design", {"email_patch": {"design": {"body": {}}}}),
            ("html", {"email_patch": {"html": "<p>sneaky</p>"}}),
            ("empty", {"email_patch": {}}),
            ("non_object", {"email_patch": "subject"}),
        ]
    )
    def test_email_patch_rejects_bad_payloads(self, _name, payload):
        function_id = self._create_email_function()

        response = self._patch_email(function_id, payload)

        assert response.status_code == status.HTTP_400_BAD_REQUEST
        assert self._stored_email_value(function_id) == EMAIL_VALUE

    def test_requires_operations_or_email_patch(self):
        function_id = self._create_email_function()

        response = self._patch_email(function_id, {})

        assert response.status_code == status.HTTP_400_BAD_REQUEST

    def test_patch_on_non_email_function_rejected(self):
        function_id = self._create(**BASE_FUNCTION)

        response = self._patch_email(function_id, {"email_patch": {"subject": "New"}})

        assert response.status_code == status.HTTP_400_BAD_REQUEST

    def test_operations_without_design_rejected(self):
        no_design_value = {k: v for k, v in EMAIL_VALUE.items() if k != "design"}
        function_id = self._create_email_function(
            inputs={**EMAIL_FUNCTION["inputs"], "email": {"value": no_design_value}}
        )

        response = self._patch_email(
            function_id, {"operations": [{"op": "update_content", "id": "txt1", "patch": {"values": {}}}]}
        )

        assert response.status_code == status.HTTP_400_BAD_REQUEST
        assert "design" in str(response.json())

    @patch(RENDER_PATH, return_value="<p>Rendered</p>")
    def test_unknown_content_id_rejected_without_partial_write(self, _mock_render):
        function_id = self._create_email_function()

        response = self._patch_email(
            function_id,
            {
                "operations": [{"op": "update_content", "id": "nope", "patch": {"values": {"text": "x"}}}],
                "email_patch": {"subject": "Should not land"},
            },
        )

        assert response.status_code == status.HTTP_400_BAD_REQUEST
        assert self._stored_email_value(function_id) == EMAIL_VALUE

    @parameterized.expand(
        [
            ("not_configured", UnlayerNotConfiguredError("no key")),
            ("render_failed", UnlayerRenderError("upstream 500")),
        ]
    )
    def test_render_failure_rejected_without_partial_write(self, _name, error):
        function_id = self._create_email_function()

        with patch(RENDER_PATH, side_effect=error):
            response = self._patch_email(
                function_id,
                {"operations": [{"op": "update_content", "id": "txt1", "patch": {"values": {"text": "<p>New</p>"}}}]},
            )

        assert response.status_code == status.HTTP_400_BAD_REQUEST
        assert self._stored_email_value(function_id) == EMAIL_VALUE

    # --- PATCH: draft routing ---

    def test_agent_patch_on_enabled_destination_stages_draft(self):
        function_id = self._create_email_function()

        with patch(RELOAD_PATH) as mock_reload:
            response = self._agent_patch_email(function_id, {"email_patch": {"subject": "Staged"}})

        assert response.status_code == status.HTTP_200_OK, response.json()
        assert self._staged_email_value(function_id)["subject"] == "Staged"
        assert HogFunction.objects.get(id=function_id).draft_updated_at is not None
        # Workers keep running the config a human last approved.
        assert self._stored_email_value(function_id)["subject"] == "Welcome!"
        mock_reload.assert_not_called()

    def test_agent_patch_composes_on_existing_draft(self):
        function_id = self._create_email_function()
        self._agent_patch_email(function_id, {"email_patch": {"subject": "First staged"}})

        response = self._agent_patch_email(function_id, {"email_patch": {"preheader": "Second staged"}})

        assert response.status_code == status.HTTP_200_OK, response.json()
        staged = self._staged_email_value(function_id)
        # The second patch must see the first: draft edits compose, they don't reset.
        assert staged["subject"] == "First staged"
        assert staged["preheader"] == "Second staged"

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
    def test_email_patch_applies_live(self, _name, from_agent, overrides, flag_on):
        function_id = self._create_email_function(**overrides)

        with patch(FLAG_PATH, return_value=flag_on):
            response = (
                self._agent_patch_email(function_id, {"email_patch": {"subject": "Landed live"}})
                if from_agent
                else self._patch_email(function_id, {"email_patch": {"subject": "Landed live"}})
            )

        assert response.status_code == status.HTTP_200_OK, response.json()
        assert HogFunction.objects.get(id=function_id).draft is None
        assert self._stored_email_value(function_id)["subject"] == "Landed live"

    # --- secrets and revisions ---

    def test_secret_inputs_survive_live_and_draft_email_patches(self):
        function_id = self._create_email_function()
        live_secret = deepcopy(HogFunction.objects.get(id=function_id).encrypted_inputs)
        assert live_secret["api_key"]["value"] == "live-secret"

        self._patch_email(function_id, {"email_patch": {"subject": "Live edit"}})
        function = HogFunction.objects.get(id=function_id)
        assert function.encrypted_inputs == live_secret

        self._agent_patch_email(function_id, {"email_patch": {"subject": "Draft edit"}})
        function = HogFunction.objects.get(id=function_id)
        # The draft snapshot carries the live secret so publish restores it; live secrets untouched.
        assert function.encrypted_inputs == live_secret
        assert function.draft is not None and function.draft_encrypted_inputs is not None
        assert function.draft_encrypted_inputs["api_key"]["value"] == "live-secret"
        assert "api_key" not in function.draft["inputs"]

    def test_live_email_patch_records_a_revision(self):
        function_id = self._create_email_function()
        assert not self._revisions(function_id).exists()

        self._patch_email(function_id, {"email_patch": {"subject": "Versioned"}})

        function = HogFunction.objects.get(id=function_id)
        assert function.version == 2
        versions = sorted(revision.version for revision in self._revisions(function_id))
        # The first tracked write also bootstraps a snapshot of the pre-change state (version 1).
        assert versions == [1, 2]
