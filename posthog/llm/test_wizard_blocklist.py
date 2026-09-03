import pytest
from unittest.mock import patch

from posthog.llm.wizard_blocklist import blocklist_flag_defined, blocklist_properties, wizard_identity_blocked


class TestBlocklistProperties:
    @pytest.mark.parametrize(
        "email,expected_root,expected_domain",
        [
            ("sample.user+7@gmail.com", "sampleuser@gmail.com", "gmail.com"),
            ("sample.user@gmail.com", "sampleuser@gmail.com", "gmail.com"),
            ("sampleuser@googlemail.com", "sampleuser@gmail.com", "googlemail.com"),
            ("  Sample.User+9@Gmail.com ", "sampleuser@gmail.com", "gmail.com"),
            # Dots alias only at Gmail; elsewhere they identify the mailbox.
            ("a.b+c@example.net", "a.b@example.net", "example.net"),
            ("22@example.com", "22@example.com", "example.com"),
            ("+only@example.org", "@example.org", "example.org"),
            ('"a@b"@example.net', '"a@b"@example.net', "example.net"),
        ],
    )
    def test_derives_the_keys_an_abuse_report_names(self, email, expected_root, expected_domain):
        properties = blocklist_properties(email=email, organization_id="org_1", team_id=7)

        assert properties["email"] == email.strip().lower()
        assert properties["email_root"] == expected_root
        assert properties["email_domain"] == expected_domain

    @pytest.mark.parametrize("email", [None, "", "   ", "nodomain"])
    def test_an_unusable_address_still_carries_every_key(self, email):
        properties = blocklist_properties(email=email, organization_id="org_1", team_id=7)

        # A missing key would make a condition on it silently never match.
        assert set(properties) == {"email", "email_root", "email_domain", "organization_id", "team_id"}
        assert properties["email_domain"] == ""
        assert properties["organization_id"] == "org_1"
        assert properties["team_id"] == "7"


class TestWizardIdentityBlocked:
    def test_evaluates_the_flag_with_every_match_key(self):
        with patch(
            "posthog.llm.wizard_blocklist.posthoganalytics.feature_enabled", return_value=True
        ) as feature_enabled:
            blocked = wizard_identity_blocked(
                distinct_id="d1",
                email="22@example.com",
                organization_id="org_1",
                team_id=7,
                surface="gateway_token",
            )

        assert blocked is True
        feature_enabled.assert_called_once_with(
            "wizard-gateway-blocklist",
            "d1",
            person_properties={
                "email": "22@example.com",
                "email_root": "22@example.com",
                "email_domain": "example.com",
                "organization_id": "org_1",
                "team_id": "7",
            },
            only_evaluate_locally=True,
            send_feature_flag_events=False,
        )

    def test_an_unlisted_identity_is_not_blocked(self):
        with patch("posthog.llm.wizard_blocklist.posthoganalytics.feature_enabled", return_value=False):
            assert (
                wizard_identity_blocked(
                    distinct_id="d1",
                    email="eng@posthog.com",
                    organization_id="org_1",
                    team_id=7,
                    surface="gateway_token",
                )
                is False
            )

    def test_the_lookup_never_leaves_the_process(self):
        # A gate on /oauth/authorize must not add an outbound call to every grant.
        with patch(
            "posthog.llm.wizard_blocklist.posthoganalytics.feature_enabled", return_value=True
        ) as feature_enabled:
            wizard_identity_blocked(distinct_id="d1", email="22@example.com", surface="revoke_sweep")

        assert feature_enabled.call_args.kwargs["only_evaluate_locally"] is True

    def test_an_undecidable_flag_is_counted_apart_from_an_unlisted_identity(self):
        with (
            patch("posthog.llm.wizard_blocklist.posthoganalytics.feature_enabled", return_value=None),
            patch("posthog.llm.wizard_blocklist.blocklist_flag_defined", return_value=True),
            patch("posthog.llm.wizard_blocklist.WIZARD_BLOCKLIST_CHECKS") as checks,
        ):
            assert wizard_identity_blocked(distinct_id="d1", email="22@example.com", surface="query") is False

        assert checks.labels.call_args.kwargs == {"surface": "query", "outcome": "inconclusive"}

    def test_a_missing_flag_is_not_reported_as_undecidable(self):
        with (
            patch("posthog.llm.wizard_blocklist.posthoganalytics.feature_enabled", return_value=None),
            patch("posthog.llm.wizard_blocklist.blocklist_flag_defined", return_value=False),
            patch("posthog.llm.wizard_blocklist.WIZARD_BLOCKLIST_CHECKS") as checks,
        ):
            wizard_identity_blocked(distinct_id="d1", email="22@example.com", surface="query")

        assert checks.labels.call_args.kwargs == {"surface": "query", "outcome": "unconfigured"}

    def test_an_unknown_org_and_team_still_carry_their_keys(self):
        properties = blocklist_properties(email="22@example.com")

        # OAuth consent pins no project, and an address ban still has to land.
        assert properties["organization_id"] == ""
        assert properties["team_id"] == ""
        assert properties["email_domain"] == "example.com"

    @pytest.mark.parametrize("outcome", [{"side_effect": RuntimeError("down")}, {"return_value": None}])
    def test_a_flag_outage_fails_open(self, outcome):
        # Losing the blocklist must not refuse every wizard run.
        with patch("posthog.llm.wizard_blocklist.posthoganalytics.feature_enabled", **outcome):
            assert (
                wizard_identity_blocked(
                    distinct_id="d1",
                    email="22@example.com",
                    organization_id="org_1",
                    team_id=7,
                    surface="gateway_token",
                )
                is False
            )


class TestBlocklistFlagDefined:
    @pytest.mark.parametrize(
        "definitions,expected",
        [
            # The SDK returns data["flags"] verbatim: a list of dicts, or None
            # before local evaluation has loaded any.
            ([{"key": "wizard-gateway-blocklist"}, {"key": "other"}], True),
            ([{"key": "other"}], False),
            ([], False),
            (None, False),
            ({"flags": [{"key": "wizard-gateway-blocklist"}]}, True),
        ],
    )
    def test_reads_the_shape_the_sdk_actually_returns(self, definitions, expected):
        with patch("posthog.llm.wizard_blocklist.posthoganalytics.feature_flag_definitions", return_value=definitions):
            assert blocklist_flag_defined() is expected

    def test_an_sdk_error_is_not_a_definition(self):
        with patch(
            "posthog.llm.wizard_blocklist.posthoganalytics.feature_flag_definitions",
            side_effect=RuntimeError("down"),
        ):
            assert blocklist_flag_defined() is False
