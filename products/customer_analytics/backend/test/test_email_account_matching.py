from itertools import count

from posthog.test.base import BaseTest
from unittest.mock import MagicMock, call, patch

from django.core.cache import cache

from parameterized import parameterized

from posthog.models.organization import Organization, OrganizationMembership
from posthog.models.user import User

from products.conversations.backend.facade.types import EmailThreadForAccountMatching
from products.customer_analytics.backend.facade import api
from products.customer_analytics.backend.facade.email_matching import (
    finish_email_thread_link_recalculation,
    match_email_accounts,
    recalculate_email_thread_links,
    recalculate_email_thread_links_for_account_properties,
    schedule_email_thread_link_recalculation,
    schedule_email_thread_link_recalculation_for_threads,
)
from products.customer_analytics.backend.logic.email_account_matching import (
    MatchedAccount,
    match_accounts_for_account_properties,
    match_accounts_for_gmail_emails,
)
from products.customer_analytics.backend.models import Account


class TestEmailAccountMatching(BaseTest):
    def _create_account(
        self,
        *,
        name: str,
        external_id: str,
        known_emails: list[str] | None = None,
        email_domains: list[str] | None = None,
    ) -> Account:
        return Account.objects.for_team(self.team.id).create(
            team=self.team,
            name=name,
            external_id=external_id,
            _properties={
                "known_emails": known_emails or [],
                "email_domains": email_domains or [],
            },
        )

    @parameterized.expand([("unique_group", "group-account"), ("ambiguous_group", None)])
    @patch("products.customer_analytics.backend.logic.email_account_matching.resolve_group_keys_by_email")
    def test_matches_multiple_accounts_with_explicit_precedence(
        self, _name: str, lower_priority_group_key: str | None, mock_group_keys: MagicMock
    ) -> None:
        self.team.customer_analytics_config.account_group_type_index = 0
        self.team.customer_analytics_config.save(update_fields=["account_group_type_index"])
        known = self._create_account(
            name="Known",
            external_id="known-account",
            known_emails=["known@shared.example.com"],
            email_domains=["shared.example.com"],
        )
        grouped = self._create_account(name="Grouped", external_id="group-account")
        domain = self._create_account(
            name="Domain",
            external_id="domain-account",
            email_domains=["shared.example.com", "domain.example.com"],
        )
        mock_group_keys.side_effect = lambda _team_id, emails, _index: {
            email: "group-account" if email == "person@group.example.com" else lower_priority_group_key
            for email in emails
        }

        matches = match_email_accounts(
            self.team.id,
            ["known@shared.example.com", "person@group.example.com", "contact@domain.example.com"],
        )

        assert {(match.account_id, match.match_source) for match in matches} == {
            (str(known.id), "known_email"),
            (str(grouped.id), "person_group"),
            (str(domain.id), "email_domain"),
        }

    @parameterized.expand([("known_email",), ("person_group",), ("email_domain",)])
    @patch("products.customer_analytics.backend.logic.email_account_matching.resolve_group_keys_by_email")
    def test_posthog_email_is_excluded_from_all_matching_steps(self, source: str, mock_group_keys: MagicMock) -> None:
        self.team.customer_analytics_config.account_group_type_index = 0
        self.team.customer_analytics_config.save(update_fields=["account_group_type_index"])
        self._create_account(
            name="Internal account",
            external_id="internal-account",
            known_emails=["member@posthog.com"] if source == "known_email" else [],
            email_domains=["posthog.com"] if source == "email_domain" else [],
        )
        customer = self._create_account(name="Customer", external_id="customer", email_domains=["example.com"])
        mock_group_keys.side_effect = lambda _team_id, emails, _index: {
            email: "internal-account" for email in emails if email == "member@posthog.com" and source == "person_group"
        }

        matches = match_email_accounts(self.team.id, [" Member@PostHog.com ", "contact@example.com"])

        assert [(match.account_id, match.match_source) for match in matches] == [(str(customer.id), "email_domain")]
        assert match_email_accounts(self.team.id, ["member@posthog.com"]) == []
        gmail_matches = match_accounts_for_gmail_emails(self.team, [" Member@PostHog.com ", "contact@example.com"])
        assert [(email, match.account.id, match.source) for email, match in gmail_matches.items()] == [
            ("contact@example.com", customer.id, "email_domain")
        ]

    def _create_account_member(self, *, email: str, organization: Organization | None = None) -> User:
        member = User.objects.create(email=email)
        OrganizationMembership.objects.create(user=member, organization=organization or self.organization)
        return member

    @parameterized.expand(
        [
            ("no_domain", 0, "organization_member"),
            ("unique_domain", 1, "email_domain"),
            ("ambiguous_domain", 2, None),
        ]
    )
    def test_matches_organization_member_for_gmail_email(
        self, _name: str, domain_account_count: int, expected_source: str | None
    ) -> None:
        member = self._create_account_member(email="member@example.com")
        member_account = self._create_account(name="Member", external_id=str(self.organization.id))
        domain_accounts = [
            self._create_account(
                name=f"Domain {index}", external_id=f"domain-account-{index}", email_domains=["example.com"]
            )
            for index in range(domain_account_count)
        ]

        matches = match_accounts_for_gmail_emails(self.team, [member.email])

        if expected_source is None:
            assert matches == {}
        else:
            expected_account = domain_accounts[0] if domain_accounts else member_account
            assert [(str(match.account.id), match.source) for match in matches.values()] == [
                (str(expected_account.id), expected_source)
            ]

    def test_direct_matching_does_not_use_organization_membership(self) -> None:
        member = self._create_account_member(email="member@gmail.com")
        self._create_account(name="Customer", external_id=str(self.organization.id))

        matches = match_email_accounts(self.team.id, [member.email])

        assert matches == []
        assert match_accounts_for_account_properties(self.team, [member.email]) == {}

    def test_gmail_membership_skips_only_posthog_domain(self) -> None:
        posthog_member = self._create_account_member(email="Member@PostHog.com")
        subdomain_member = self._create_account_member(email="member@eu.posthog.com")
        account = self._create_account(name="Customer", external_id=str(self.organization.id))

        matches = match_accounts_for_gmail_emails(self.team, [posthog_member.email, subdomain_member.email])

        assert [(email, str(match.account.id), match.source) for email, match in matches.items()] == [
            (subdomain_member.email, str(account.id), "organization_member")
        ]

    def test_matches_a_mixed_case_organization_member_email(self) -> None:
        self._create_account_member(email="Member@Gmail.com")
        account = self._create_account(name="Customer", external_id=str(self.organization.id))

        matches = match_accounts_for_gmail_emails(self.team, ["member@gmail.com"])

        assert [(str(match.account.id), match.source) for match in matches.values()] == [
            (str(account.id), "organization_member")
        ]

    def test_does_not_match_case_folded_duplicate_users(self) -> None:
        self._create_account_member(email="member@gmail.com")
        other_organization = Organization.objects.create(name="Other customer")
        self._create_account_member(email="Member@Gmail.com", organization=other_organization)
        self._create_account(name="First customer", external_id=str(self.organization.id))
        self._create_account(name="Second customer", external_id=str(other_organization.id))

        matches = match_accounts_for_gmail_emails(self.team, ["member@gmail.com"])

        assert matches == {}

    def test_does_not_match_an_organization_member_of_multiple_accounts(self) -> None:
        member = self._create_account_member(email="member@gmail.com")
        other_organization = Organization.objects.create(name="Other customer")
        OrganizationMembership.objects.create(user=member, organization=other_organization)
        self._create_account(name="First customer", external_id=str(self.organization.id))
        self._create_account(name="Second customer", external_id=str(other_organization.id))

        matches = match_accounts_for_gmail_emails(self.team, [member.email])

        assert matches == {}

    @patch(
        "products.customer_analytics.backend.logic.email_account_matching.resolve_group_keys_by_email",
        return_value={},
    )
    def test_ambiguous_known_email_does_not_fall_through_to_domain(self, _mock_group_keys: MagicMock) -> None:
        for external_id in ("first", "second"):
            self._create_account(
                name=external_id,
                external_id=external_id,
                known_emails=["shared@ambiguous.example"],
            )
        self._create_account(
            name="Domain fallback",
            external_id="domain-fallback",
            email_domains=["ambiguous.example"],
        )

        matches = match_email_accounts(self.team.id, ["shared@ambiguous.example"])

        assert matches == []

    @patch("products.customer_analytics.backend.facade.email_matching.conversations.replace_email_thread_account_links")
    @patch(
        "products.customer_analytics.backend.facade.email_matching.conversations.list_email_threads_for_account_matching"
    )
    @patch("products.customer_analytics.backend.facade.email_matching.match_accounts_for_emails")
    def test_recalculation_matches_once_per_page_and_maps_links_per_thread(
        self,
        mock_match: MagicMock,
        mock_list_threads: MagicMock,
        mock_replace: MagicMock,
    ) -> None:
        first = self._create_account(name="First", external_id="first-account")
        second = self._create_account(name="Second", external_id="second-account")
        mock_list_threads.side_effect = [
            [
                EmailThreadForAccountMatching(
                    id="thread-1",
                    participant_emails=["First.Person@Example.com", "contact@first.example.com"],
                    gmail_owner_id=None,
                ),
                EmailThreadForAccountMatching(
                    id="thread-2",
                    participant_emails=["known@second.example.com", "contact@second.example.com"],
                    gmail_owner_id=None,
                ),
            ],
            [],
        ]
        mock_match.return_value = {
            "first.person@example.com": MatchedAccount(account=first, source="person_group"),
            "contact@first.example.com": MatchedAccount(account=first, source="email_domain"),
            "known@second.example.com": MatchedAccount(account=second, source="known_email"),
            "contact@second.example.com": MatchedAccount(account=second, source="email_domain"),
        }

        processed = recalculate_email_thread_links(self.team.id, batch_size=100)

        assert processed == 2
        mock_match.assert_called_once_with(
            self.team,
            [
                "First.Person@Example.com",
                "contact@first.example.com",
                "known@second.example.com",
                "contact@second.example.com",
            ],
        )
        links_by_thread = {call.args[1]: call.args[2] for call in mock_replace.call_args_list}
        assert [
            (link.account_id, link.account_external_id, link.match_source) for link in links_by_thread["thread-1"]
        ] == [(str(first.id), "first-account", "email_domain")]
        assert [(link.account_id, link.match_source) for link in links_by_thread["thread-2"]] == [
            (str(second.id), "known_email")
        ]

    @parameterized.expand(
        [
            ("domain_removed", False),
            ("domain_added", False),
            ("known_email_ambiguous", False),
            ("domain_removed", True),
        ]
    )
    @patch("products.customer_analytics.backend.facade.email_matching.current_app.send_task")
    @patch("products.customer_analytics.backend.facade.email_matching.randbits", side_effect=count(1))
    @patch("products.customer_analytics.backend.facade.email_matching.conversations.replace_email_thread_account_links")
    @patch(
        "products.customer_analytics.backend.facade.email_matching.conversations.list_email_threads_for_account_matching"
    )
    @patch("products.customer_analytics.backend.logic.email_account_matching.resolve_group_keys_by_email")
    def test_full_recalculation_refreshes_properties_after_a_targeted_rematch(
        self,
        change: str,
        evict_revision: bool,
        mock_group_keys: MagicMock,
        mock_list_threads: MagicMock,
        mock_replace: MagicMock,
        _mock_randbits: MagicMock,
        _mock_send_task: MagicMock,
    ) -> None:
        self.team.customer_analytics_config.account_group_type_index = 0
        self.team.customer_analytics_config.save(update_fields=["account_group_type_index"])
        previous_domains = ["old.example.com"] if change == "domain_removed" else []
        property_account = self._create_account(
            name="Property match", external_id="property-account", email_domains=previous_domains
        )
        identity_account = self._create_account(name="Identity match", external_id="identity-account")
        competing_account = (
            self._create_account(name="Competing match", external_id="competing-account")
            if change == "known_email_ambiguous"
            else None
        )
        mock_list_threads.return_value = [
            EmailThreadForAccountMatching(
                id="affected-thread",
                participant_emails=["contact@old.example.com", "person@identity.example.com"],
                gmail_owner_id=None,
            )
        ]

        def resolve_groups_during_property_edit(_team_id: int, _emails: list[str], _index: int) -> dict[str, str]:
            with self.captureOnCommitCallbacks(execute=True):
                if change == "known_email_ambiguous":
                    assert competing_account is not None
                    api.update_account(
                        competing_account,
                        properties={"known_emails": ["person@identity.example.com"]},
                        allow_matching_updates=True,
                    )
                    properties = {"known_emails": ["person@identity.example.com"]}
                else:
                    properties = {"email_domains": ["identity.example.com"] if change == "domain_added" else []}
                api.update_account(property_account, properties=properties, allow_matching_updates=True)

            recalculate_email_thread_links_for_account_properties(
                self.team.id,
                str(property_account.id),
                previous_known_emails=[],
                previous_email_domains=previous_domains,
            )
            if evict_revision:
                cache.clear()
            return {"person@identity.example.com": "identity-account"}

        mock_group_keys.side_effect = resolve_groups_during_property_edit

        processed = recalculate_email_thread_links(self.team.id)

        assert processed == 1
        mock_group_keys.assert_called_once()
        final_links = {(link.account_id, link.match_source) for link in mock_replace.call_args.args[2]}
        if change == "domain_removed":
            assert final_links == {(str(identity_account.id), "person_group")}
        elif change == "domain_added":
            assert final_links == {(str(property_account.id), "email_domain")}
        else:
            assert final_links == set()

    @patch("products.customer_analytics.backend.facade.email_matching.conversations.replace_email_thread_account_links")
    @patch(
        "products.customer_analytics.backend.facade.email_matching.conversations.list_email_threads_for_account_matching"
    )
    @patch("products.customer_analytics.backend.logic.account_member_search.posthog_feature_flag_enabled")
    def test_recalculation_checks_each_gmail_owner_without_sharing_matches(
        self,
        mock_flag: MagicMock,
        mock_list_threads: MagicMock,
        mock_replace: MagicMock,
    ) -> None:
        self.user.is_staff = True
        self.user.save(update_fields=["is_staff"])
        disabled_owner = User.objects.create(
            email="disabled-owner@posthog.com",
            is_staff=True,
            distinct_id="disabled-owner",
        )
        nonstaff_owner = User.objects.create(
            email="nonstaff-owner@example.com",
            distinct_id="nonstaff-owner",
        )
        inactive_owner = User.objects.create(
            email="inactive-owner@posthog.com",
            is_active=False,
            is_staff=True,
            distinct_id="inactive-owner",
        )
        member = self._create_account_member(email="member@gmail.com")
        account = self._create_account(name="Customer", external_id=str(self.organization.id))
        mock_flag.side_effect = lambda _flag, distinct_id, **_kwargs: distinct_id == str(self.user.distinct_id)
        mock_list_threads.return_value = [
            EmailThreadForAccountMatching(
                id="enabled-thread",
                participant_emails=[member.email],
                gmail_owner_id=self.user.id,
            ),
            EmailThreadForAccountMatching(
                id="disabled-thread",
                participant_emails=[member.email],
                gmail_owner_id=disabled_owner.id,
            ),
            EmailThreadForAccountMatching(
                id="nonstaff-thread",
                participant_emails=[member.email],
                gmail_owner_id=nonstaff_owner.id,
            ),
            EmailThreadForAccountMatching(
                id="inactive-thread",
                participant_emails=[member.email],
                gmail_owner_id=inactive_owner.id,
            ),
        ]

        processed = recalculate_email_thread_links(self.team.id)

        assert processed == 4
        assert {call.args[1] for call in mock_flag.call_args_list} == {
            str(self.user.distinct_id),
            "disabled-owner",
        }
        links_by_thread = {call.args[1]: call.args[2] for call in mock_replace.call_args_list}
        assert [(link.account_id, link.match_source) for link in links_by_thread["enabled-thread"]] == [
            (str(account.id), "organization_member")
        ]
        assert links_by_thread["disabled-thread"] == []
        assert links_by_thread["nonstaff-thread"] == []
        assert links_by_thread["inactive-thread"] == []

    @patch("products.customer_analytics.backend.facade.email_matching.conversations.replace_email_thread_account_links")
    @patch(
        "products.customer_analytics.backend.facade.email_matching.conversations.list_email_threads_for_account_matching"
    )
    @patch("products.customer_analytics.backend.logic.email_account_matching.resolve_group_keys_by_email")
    def test_property_recalculation_skips_identity_matching_and_limits_threads(
        self,
        mock_group_keys: MagicMock,
        mock_list_threads: MagicMock,
        mock_replace: MagicMock,
    ) -> None:
        self.team.customer_analytics_config.account_group_type_index = 0
        self.team.customer_analytics_config.save(update_fields=["account_group_type_index"])
        account = self._create_account(
            name="Customer",
            external_id="customer",
            known_emails=["contact@billing.example.com"],
            email_domains=["new.example.com"],
        )
        self._create_account(name="Identity only", external_id="identity-account")
        mock_group_keys.return_value = {"person@identity.example.com": "identity-account"}
        mock_list_threads.side_effect = [
            [
                EmailThreadForAccountMatching(
                    id="thread-1",
                    participant_emails=["Contact@Billing.Example.com", "legacy@billing.example.com"],
                    gmail_owner_id=self.user.id,
                ),
                EmailThreadForAccountMatching(
                    id="thread-2",
                    participant_emails=["person@new.example.com"],
                    gmail_owner_id=None,
                ),
            ],
            [
                EmailThreadForAccountMatching(
                    id="thread-3",
                    participant_emails=["person@old.example.com"],
                    gmail_owner_id=None,
                ),
                EmailThreadForAccountMatching(
                    id="thread-4",
                    participant_emails=["legacy@billing.example.com", "person@identity.example.com"],
                    gmail_owner_id=self.user.id,
                ),
            ],
            [],
        ]

        processed = recalculate_email_thread_links_for_account_properties(
            self.team.id,
            str(account.id),
            previous_known_emails=["contact@billing.example.com", "legacy@billing.example.com"],
            previous_email_domains=["old.example.com"],
            batch_size=2,
        )

        assert processed == 4
        mock_group_keys.assert_not_called()
        assert [
            (item.args[1], [(link.account_id, link.match_source) for link in item.args[2]])
            for item in mock_replace.call_args_list
        ] == [
            ("thread-1", [(str(account.id), "known_email")]),
            ("thread-2", [(str(account.id), "email_domain")]),
            ("thread-3", []),
            ("thread-4", []),
        ]
        assert all(
            item.kwargs == {"match_sources": ["known_email", "email_domain"]} for item in mock_replace.call_args_list
        )
        assert mock_list_threads.call_args_list == [
            call(
                self.team.id,
                participant_emails=["legacy@billing.example.com"],
                participant_domains=["new.example.com", "old.example.com"],
                after_id=after_id,
                limit=2,
            )
            for after_id in (None, "thread-2", "thread-4")
        ]

    @parameterized.expand(
        [
            (
                "known_email_changed",
                {"known_emails": ["other@example.com"], "email_domains": ["old.example.com"]},
                True,
            ),
            (
                "email_domain_changed",
                {"known_emails": ["person@example.com"], "email_domains": ["new.example.com"]},
                True,
            ),
            ("matching_removed", {"known_emails": [], "email_domains": []}, True),
            (
                "unrelated_property_changed",
                {
                    "known_emails": ["person@example.com"],
                    "email_domains": ["old.example.com"],
                    "sfdc_id": "example-salesforce-account",
                },
                False,
            ),
            (
                "matching_unchanged_after_normalization",
                {"known_emails": [" Person@Example.com "], "email_domains": ["@OLD.EXAMPLE.COM"]},
                False,
            ),
        ]
    )
    @patch("products.customer_analytics.backend.facade.email_matching.current_app.send_task")
    def test_account_matching_changes_schedule_recalculation(
        self, _name: str, properties: dict[str, list[str] | str], expected_rematch: bool, mock_send_task: MagicMock
    ) -> None:
        with self.captureOnCommitCallbacks(execute=True):
            account = api.create_account(
                team=self.team,
                name="Account",
                external_id="account",
                properties={"known_emails": ["person@example.com"], "email_domains": ["old.example.com"]},
            )
        mock_send_task.reset_mock()

        with self.captureOnCommitCallbacks(execute=True):
            api.update_account(
                account, external_id=account.external_id, properties=properties, allow_matching_updates=True
            )
            assert not any("recalculate_email_thread" in item.args[0] for item in mock_send_task.call_args_list)

        email_rematches = [item for item in mock_send_task.call_args_list if "recalculate_email_thread" in item.args[0]]
        assert email_rematches == (
            [
                call(
                    "customer_analytics.recalculate_email_thread_account_links_for_account_properties",
                    args=[self.team.id, str(account.id)],
                    kwargs={
                        "previous_known_emails": ["person@example.com"],
                        "previous_email_domains": ["old.example.com"],
                    },
                )
            ]
            if expected_rematch
            else []
        )

    @parameterized.expand(
        [
            ("active_run", False, False),
            ("run_finished_during_schedule", True, True),
        ]
    )
    @patch("products.customer_analytics.backend.facade.email_matching.current_app.send_task")
    @patch("products.customer_analytics.backend.facade.email_matching.cache")
    def test_recalculation_requested_during_a_run_is_not_lost(
        self,
        _name: str,
        second_lock_acquired: bool,
        expected_enqueue: bool,
        mock_cache: MagicMock,
        mock_send_task: MagicMock,
    ) -> None:
        mock_cache.add.side_effect = [False, second_lock_acquired]

        with self.captureOnCommitCallbacks(execute=True):
            schedule_email_thread_link_recalculation(self.team.id)

        mock_cache.set.assert_called_once()
        if expected_enqueue:
            mock_send_task.assert_called_once()
        else:
            mock_send_task.assert_not_called()

    @patch("products.customer_analytics.backend.facade.email_matching.current_app.send_task")
    def test_targeted_recalculation_is_enqueued_after_commit(self, mock_send_task: MagicMock) -> None:
        with self.captureOnCommitCallbacks(execute=True):
            schedule_email_thread_link_recalculation_for_threads(self.team.id, ["thread-1", "thread-1"])

        mock_send_task.assert_called_once_with(
            "customer_analytics.recalculate_email_thread_account_links_for_threads",
            args=[self.team.id, ["thread-1"]],
        )

    @patch("products.customer_analytics.backend.facade.email_matching.schedule_email_thread_link_recalculation")
    @patch("products.customer_analytics.backend.facade.email_matching.cache")
    def test_finished_recalculation_schedules_dirty_follow_up(
        self, mock_cache: MagicMock, mock_schedule: MagicMock
    ) -> None:
        mock_cache.delete.side_effect = [True, True]

        finish_email_thread_link_recalculation(self.team.id)

        mock_schedule.assert_called_once_with(self.team.id)
