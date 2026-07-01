import hmac
import json
import hashlib
from uuid import uuid4

from posthog.test.base import APIBaseTest
from unittest.mock import patch

from django.test import TestCase, override_settings

from parameterized import parameterized

from posthog.api.linear_agent_webhook import verify_linear_signature
from posthog.models.integration import Integration

from products.tasks.backend.facade import api as tasks_facade

WEBHOOK_PATH = "/api/linear-agent/webhook"
SECRET = "linear-webhook-secret"
ORG_ID = "org-abc"
BOT_ID = "bot-user-123"
ISSUE_UUID = "11111111-2222-3333-4444-555555555555"
ISSUE_URL = "https://linear.app/acme/issue/ENG-42/fix-it"


def _sign(body: bytes, secret: str = SECRET) -> str:
    return hmac.new(secret.encode("utf-8"), body, hashlib.sha256).hexdigest()


class TestLinearSignatureVerification(TestCase):
    @parameterized.expand(
        [
            ("valid", SECRET, True),
            ("tampered_secret", "wrong-secret", False),
        ]
    )
    def test_signature_matches_only_with_correct_secret(self, _name, signing_secret, expected):
        body = b'{"hello":"world"}'
        signature = _sign(body, signing_secret)
        self.assertEqual(verify_linear_signature(body, signature, SECRET), expected)

    def test_rejects_signature_for_tampered_body(self):
        signature = _sign(b'{"amount":1}')
        self.assertFalse(verify_linear_signature(b'{"amount":1000000}', signature, SECRET))

    @parameterized.expand([("missing_signature", None), ("empty_signature", "")])
    def test_rejects_missing_signature(self, _name, signature):
        self.assertFalse(verify_linear_signature(b"{}", signature, SECRET))

    def test_rejects_when_secret_unset(self):
        self.assertFalse(verify_linear_signature(b"{}", _sign(b"{}"), ""))


@override_settings(LINEAR_AGENT_WEBHOOK_SECRET=SECRET)
class TestLinearAgentWebhook(APIBaseTest):
    def setUp(self):
        super().setUp()
        self.integration = Integration.objects.create(
            team=self.team,
            kind="linear-agent",
            integration_id=ORG_ID,
            config={
                "data": {"viewer": {"id": BOT_ID, "organization": {"id": ORG_ID, "name": "Acme", "urlKey": "acme"}}}
            },
            sensitive_config={"access_token": "tok", "refresh_token": "ref"},
            created_by=self.user,
        )

    def _assignment_payload(self, *, type="Issue", action="update", org=ORG_ID, delegate=BOT_ID, updated_from=None):
        return {
            "type": type,
            "action": action,
            "organizationId": org,
            "data": {
                "id": ISSUE_UUID,
                "identifier": "ENG-42",
                "title": "Fix the thing",
                "description": "Make it work",
                "url": ISSUE_URL,
                "delegateId": delegate,
            },
            "updatedFrom": {"delegateId": None} if updated_from is None else updated_from,
        }

    def _post(self, payload, *, signature=None, delivery=None):
        body = json.dumps(payload).encode("utf-8")
        # Unique per call so the Redis delivery-id dedup never leaks across tests.
        headers = {"Linear-Delivery": delivery or str(uuid4())}
        headers["Linear-Signature"] = signature if signature is not None else _sign(body)
        return self.client.post(WEBHOOK_PATH, data=body, content_type="application/json", headers=headers)

    def test_rejects_invalid_signature(self):
        with patch("posthog.api.linear_agent_webhook.tasks_facade.create_and_run_task") as mock_create:
            response = self._post(self._assignment_payload(), signature="deadbeef")
        self.assertEqual(response.status_code, 403)
        mock_create.assert_not_called()

    @override_settings(LINEAR_AGENT_WEBHOOK_SECRET="")
    def test_returns_500_when_secret_unconfigured(self):
        response = self._post(self._assignment_payload())
        self.assertEqual(response.status_code, 500)

    def test_rejects_invalid_json(self):
        body = b"not json"
        response = self.client.post(
            WEBHOOK_PATH,
            data=body,
            content_type="application/json",
            headers={"Linear-Signature": _sign(body)},
        )
        self.assertEqual(response.status_code, 400)

    @patch("posthog.api.linear_agent_webhook.posthoganalytics.feature_enabled", return_value=True)
    @patch("posthog.api.linear_agent_webhook.tasks_facade.create_task_external_reference")
    @patch("posthog.api.linear_agent_webhook.tasks_facade.get_task_id_for_external_reference", return_value=None)
    @patch("posthog.api.linear_agent_webhook.tasks_facade.create_and_run_task")
    def test_assignment_to_bot_creates_task_and_reference(self, mock_create, _mock_lookup, mock_ref, _mock_flag):
        created_task_id = uuid4()
        mock_create.return_value.task_id = created_task_id

        response = self._post(self._assignment_payload())

        self.assertEqual(response.status_code, 200)
        mock_create.assert_called_once()
        kwargs = mock_create.call_args.kwargs
        self.assertEqual(kwargs["team"], self.team)
        self.assertEqual(kwargs["user_id"], self.user.id)
        self.assertEqual(kwargs["origin_product"], tasks_facade.TaskOriginProduct.LINEAR)
        self.assertIsNone(kwargs["repository"])
        self.assertIn("ENG-42", kwargs["title"])

        mock_ref.assert_called_once()
        ref_kwargs = mock_ref.call_args.kwargs
        self.assertEqual(ref_kwargs["team_id"], self.team.id)
        self.assertEqual(ref_kwargs["task_id"], created_task_id)
        self.assertEqual(ref_kwargs["kind"], "linear-issue")
        self.assertEqual(ref_kwargs["external_id"], ISSUE_UUID)
        self.assertEqual(ref_kwargs["external_url"], ISSUE_URL)

    @parameterized.expand(
        [
            ("non_issue_event", {"type": "Comment"}),
            ("assigned_to_other_user", {"delegate": "someone-else"}),
            ("unknown_organization", {"org": "org-not-connected"}),
            ("update_without_owner_transition", {"updated_from": {}}),
        ]
    )
    @patch("posthog.api.linear_agent_webhook.posthoganalytics.feature_enabled", return_value=True)
    @patch("posthog.api.linear_agent_webhook.tasks_facade.create_and_run_task")
    def test_ignored_events_do_not_create_task(self, _name, overrides, mock_create, _mock_flag):
        response = self._post(self._assignment_payload(**overrides))
        self.assertEqual(response.status_code, 200)
        mock_create.assert_not_called()

    @patch("posthog.api.linear_agent_webhook.posthoganalytics.feature_enabled", return_value=False)
    @patch("posthog.api.linear_agent_webhook.tasks_facade.create_and_run_task")
    def test_feature_flag_off_skips_task_creation(self, mock_create, _mock_flag):
        response = self._post(self._assignment_payload())
        self.assertEqual(response.status_code, 200)
        mock_create.assert_not_called()

    @patch("posthog.api.linear_agent_webhook.posthoganalytics.feature_enabled", return_value=True)
    @patch("posthog.api.linear_agent_webhook.tasks_facade.get_task_id_for_external_reference", return_value=uuid4())
    @patch("posthog.api.linear_agent_webhook.tasks_facade.create_and_run_task")
    def test_already_linked_issue_skips_task_creation(self, mock_create, _mock_lookup, _mock_flag):
        response = self._post(self._assignment_payload())
        self.assertEqual(response.status_code, 200)
        mock_create.assert_not_called()
