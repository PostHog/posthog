from posthog.test.base import BaseTest
from unittest.mock import patch

from django.test import override_settings

from posthog.llm.wizard_mint_events import (
    PERSONLESS_DISTINCT_ID,
    WIZARD_MINT_DENIED_EVENT,
    WIZARD_TOKEN_MINTED_EVENT,
    report_wizard_mint_denied,
    report_wizard_token_minted,
)

_IDENTITY_KEYS = {"user_uuid", "email", "email_root", "email_domain", "organization_id", "team_id"}


@override_settings(CLOUD_DEPLOYMENT="US")
class TestReportWizardMintDenied(BaseTest):
    def setUp(self):
        super().setUp()
        capture_patch = patch("posthog.llm.wizard_mint_events.posthoganalytics.capture")
        self.mock_capture = capture_patch.start()
        self.addCleanup(capture_patch.stop)

    def test_a_refusal_with_no_identity_is_personless(self):
        report_wizard_mint_denied(
            surface="gateway_token",
            outcome="unconfigured",
            status_code=404,
            program="integration",
            product_node="wizard:integration",
        )

        kwargs = self.mock_capture.call_args.kwargs
        assert kwargs["distinct_id"] == PERSONLESS_DISTINCT_ID
        assert kwargs["event"] == WIZARD_MINT_DENIED_EVENT
        assert kwargs["groups"] is None
        assert kwargs["properties"] == {
            "surface": "gateway_token",
            "outcome": "unconfigured",
            "status_code": 404,
            "program": "integration",
            "product_node": "wizard:integration",
            "posture": None,
            "posthog_region": "US",
            "$process_person_profile": False,
        }

    def test_a_refusal_with_a_user_and_team_carries_the_blocklist_keys_and_groups(self):
        report_wizard_mint_denied(
            surface="gateway_token",
            outcome="blocked",
            status_code=403,
            program="integration",
            product_node="wizard:integration",
            user=self.user,
            team=self.team,
        )

        kwargs = self.mock_capture.call_args.kwargs
        assert kwargs["distinct_id"] == str(self.user.distinct_id)
        properties = kwargs["properties"]
        assert _IDENTITY_KEYS <= set(properties)
        assert properties["user_uuid"] == str(self.user.uuid)
        assert properties["email"] == self.user.email.lower()
        assert properties["organization_id"] == str(self.team.organization_id)
        assert properties["team_id"] == str(self.team.id)
        # A denial must not write the address onto the person.
        assert "$set_once" not in properties
        assert "$process_person_profile" not in properties
        assert kwargs["groups"]["organization"] == str(self.organization.pk)
        assert kwargs["groups"]["project"] == str(self.team.uuid)

    def test_a_refusal_with_a_user_but_no_team_leaves_the_organization_empty(self):
        report_wizard_mint_denied(
            surface="gateway_token",
            outcome="not_wizard_app",
            status_code=401,
            program="integration",
            product_node="wizard:integration",
            user=self.user,
        )

        kwargs = self.mock_capture.call_args.kwargs
        assert kwargs["properties"]["user_uuid"] == str(self.user.uuid)
        assert kwargs["properties"]["organization_id"] == ""
        assert kwargs["properties"]["team_id"] == ""
        assert kwargs["groups"] is None

    def test_a_distinct_id_without_a_user_is_not_personless(self):
        report_wizard_mint_denied(
            surface="query",
            outcome="blocked",
            status_code=403,
            program=None,
            product_node=None,
            distinct_id="hash-only-distinct-id",
        )

        kwargs = self.mock_capture.call_args.kwargs
        assert kwargs["distinct_id"] == "hash-only-distinct-id"
        assert "$process_person_profile" not in kwargs["properties"]
        assert "user_uuid" not in kwargs["properties"]

    def test_the_program_is_bounded_and_a_non_string_is_dropped(self):
        report_wizard_mint_denied(
            surface="gateway_token",
            outcome="program_unknown",
            status_code=404,
            program="x" * 500,
            product_node=None,
        )
        assert self.mock_capture.call_args.kwargs["properties"]["program"] == "x" * 100

        report_wizard_mint_denied(
            surface="gateway_token",
            outcome="program_unknown",
            status_code=404,
            program=["integration"],
            product_node=None,
        )
        assert self.mock_capture.call_args.kwargs["properties"]["program"] == ""

    def test_a_capture_failure_is_swallowed(self):
        # The refusal is already on its way to the caller; a capture error must
        # not turn it into a 500.
        self.mock_capture.side_effect = RuntimeError("capture down")

        report_wizard_mint_denied(
            surface="gateway_token",
            outcome="blocked",
            status_code=403,
            program="integration",
            product_node="wizard:integration",
            user=self.user,
            team=self.team,
        )

        self.mock_capture.assert_called_once()


@override_settings(CLOUD_DEPLOYMENT="EU")
class TestReportWizardTokenMinted(BaseTest):
    def setUp(self):
        super().setUp()
        capture_patch = patch("posthog.llm.wizard_mint_events.posthoganalytics.capture")
        self.mock_capture = capture_patch.start()
        self.addCleanup(capture_patch.stop)

    def test_a_mint_carries_the_same_keys_as_a_denial(self):
        report_wizard_token_minted(
            program="integration",
            product_node="wizard:integration",
            user=self.user,
            team=self.team,
            cap_usd="7.000000",
            posture="paid",
        )

        kwargs = self.mock_capture.call_args.kwargs
        assert kwargs["event"] == WIZARD_TOKEN_MINTED_EVENT
        assert kwargs["properties"]["posture"] == "paid"
        assert kwargs["distinct_id"] == str(self.user.distinct_id)
        properties = kwargs["properties"]
        assert _IDENTITY_KEYS <= set(properties)
        assert properties["surface"] == "gateway_token"
        assert properties["program"] == "integration"
        assert properties["product_node"] == "wizard:integration"
        assert properties["cap_usd"] == "7.000000"
        assert properties["posthog_region"] == "EU"
        assert "outcome" not in properties
        assert kwargs["groups"]["organization"] == str(self.organization.pk)

    def test_a_missing_cap_is_reported_as_none(self):
        report_wizard_token_minted(
            program="integration", product_node="wizard:integration", user=self.user, team=self.team
        )

        assert self.mock_capture.call_args.kwargs["properties"]["cap_usd"] is None
