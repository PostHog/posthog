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
        assert set(properties) == {"user_uuid", "email", "email_root", "email_domain", "organization_id", "team_id"}
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
                user_uuid="uuid-1",
                organization_ids=["org_1"],
                team_ids=[7],
                surface="gateway_token",
            )

        assert blocked is True
        feature_enabled.assert_called_once_with(
            "wizard-gateway-blocklist",
            "d1",
            person_properties={
                "user_uuid": "uuid-1",
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
                    organization_ids=["org_1"],
                    team_ids=[7],
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
                    organization_ids=["org_1"],
                    team_ids=[7],
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


class TestMatchContexts:
    """A credential grants every organization it is scoped to, so each is asked."""

    def test_a_ban_naming_one_of_several_organizations_still_matches(self):
        # Only the second organization is named, and the sole-organization reading
        # of this credential would be "" and miss it.
        def only_org_2(_flag, _distinct_id, *, person_properties, **_kwargs):
            return person_properties["organization_id"] == "org_2"

        with patch("posthog.llm.wizard_blocklist.posthoganalytics.feature_enabled", side_effect=only_org_2):
            blocked = wizard_identity_blocked(
                distinct_id="d1",
                email="22@example.com",
                organization_ids=["org_1", "org_2", "org_3"],
                surface="revoke_sweep",
            )

        assert blocked is True

    def test_an_unnamed_organization_set_is_allowed(self):
        with patch("posthog.llm.wizard_blocklist.posthoganalytics.feature_enabled", return_value=False) as enabled:
            blocked = wizard_identity_blocked(
                distinct_id="d1",
                email="22@example.com",
                organization_ids=["org_1", "org_2"],
                surface="revoke_sweep",
            )

        assert blocked is False
        assert enabled.call_count == 2

    def test_an_organization_and_team_pair_is_asked_together(self):
        # A condition naming both only matches while they arrive in one question.
        def org_1_and_team_7(_flag, _distinct_id, *, person_properties, **_kwargs):
            return person_properties["organization_id"] == "org_1" and person_properties["team_id"] == "7"

        with patch("posthog.llm.wizard_blocklist.posthoganalytics.feature_enabled", side_effect=org_1_and_team_7):
            blocked = wizard_identity_blocked(
                distinct_id="d1", email="22@example.com", organization_ids=["org_1"], team_ids=[7], surface="query"
            )

        assert blocked is True

    def test_several_organizations_and_teams_ask_each_alone(self):
        # Which team belongs to which organization is not on the credential, so no
        # pair it never granted is invented.
        seen = []

        def record(_flag, _distinct_id, *, person_properties, **_kwargs):
            seen.append((person_properties["organization_id"], person_properties["team_id"]))
            return False

        with patch("posthog.llm.wizard_blocklist.posthoganalytics.feature_enabled", side_effect=record):
            wizard_identity_blocked(
                distinct_id="d1",
                email="22@example.com",
                organization_ids=["org_1", "org_2"],
                team_ids=[7, 8],
                surface="revoke_sweep",
            )

        assert seen == [("org_1", ""), ("org_2", ""), ("", "7"), ("", "8")]

    def test_one_outcome_is_recorded_per_check_not_per_context(self):
        with patch("posthog.llm.wizard_blocklist.posthoganalytics.feature_enabled", return_value=False):
            with patch("posthog.llm.wizard_blocklist.record_blocklist_outcome") as record:
                wizard_identity_blocked(
                    distinct_id="d1",
                    email="22@example.com",
                    organization_ids=["org_1", "org_2", "org_3"],
                    surface="revoke_sweep",
                )

        record.assert_called_once_with("revoke_sweep", "allowed")


class TestImmutableMatchKey:
    def test_the_account_uuid_is_a_match_key_an_address_change_cannot_shed(self):
        # An email-keyed ban follows the mailbox; this one follows the account.
        def only_uuid(_flag, _distinct_id, *, person_properties, **_kwargs):
            return person_properties["user_uuid"] == "uuid-1"

        with patch("posthog.llm.wizard_blocklist.posthoganalytics.feature_enabled", side_effect=only_uuid):
            blocked = wizard_identity_blocked(
                distinct_id="d1", email="moved-on@example.net", user_uuid="uuid-1", surface="oauth_authorize"
            )

        assert blocked is True
