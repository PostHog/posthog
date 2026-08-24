from posthog.test.base import BaseTest
from unittest.mock import MagicMock, patch

from parameterized import parameterized

from products.conversations.backend.facade.types import EmailThreadForAccountMatching
from products.customer_analytics.backend.facade import api
from products.customer_analytics.backend.facade.email_matching import (
    finish_email_thread_link_recalculation,
    match_email_accounts,
    recalculate_email_thread_links,
    schedule_email_thread_link_recalculation,
    schedule_email_thread_link_recalculation_for_threads,
)
from products.customer_analytics.backend.logic.email_account_matching import MatchedAccount
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

    @patch(
        "products.customer_analytics.backend.logic.email_account_matching.resolve_group_keys_by_email",
        return_value={"person@group.example": "group-account"},
    )
    def test_matches_multiple_accounts_with_explicit_precedence(self, _mock_group_keys: MagicMock) -> None:
        self.team.customer_analytics_config.account_group_type_index = 0
        self.team.customer_analytics_config.save(update_fields=["account_group_type_index"])
        known = self._create_account(
            name="Known",
            external_id="known-account",
            known_emails=["known@shared.example"],
            email_domains=["shared.example"],
        )
        grouped = self._create_account(name="Grouped", external_id="group-account")
        domain = self._create_account(
            name="Domain",
            external_id="domain-account",
            email_domains=["domain.example"],
        )

        matches = match_email_accounts(
            self.team.id,
            ["known@shared.example", "person@group.example", "contact@domain.example"],
        )

        assert {(match.account_id, match.match_source) for match in matches} == {
            (str(known.id), "known_email"),
            (str(grouped.id), "person_group"),
            (str(domain.id), "email_domain"),
        }

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
                EmailThreadForAccountMatching(id="thread-1", participant_emails=["First.Person@Example.com"]),
                EmailThreadForAccountMatching(id="thread-2", participant_emails=["contact@other.example"]),
            ],
            [],
        ]
        mock_match.return_value = {
            "first.person@example.com": MatchedAccount(account=first, source="person_group"),
            "contact@other.example": MatchedAccount(account=second, source="email_domain"),
        }

        processed = recalculate_email_thread_links(self.team.id, batch_size=100)

        assert processed == 2
        # The whole page is matched in a single pass, not once per thread.
        mock_match.assert_called_once()
        links_by_thread = {call.args[1]: call.args[2] for call in mock_replace.call_args_list}
        assert [
            (link.account_id, link.account_external_id, link.match_source) for link in links_by_thread["thread-1"]
        ] == [(str(first.id), "first-account", "person_group")]
        assert [(link.account_id, link.match_source) for link in links_by_thread["thread-2"]] == [
            (str(second.id), "email_domain")
        ]

    @patch("products.customer_analytics.backend.facade.api.schedule_email_thread_link_recalculation")
    def test_account_matching_changes_schedule_recalculation(self, mock_schedule: MagicMock) -> None:
        with self.captureOnCommitCallbacks(execute=True):
            account = api.create_account(
                team=self.team,
                name="Account",
                external_id="account",
                properties={"known_emails": ["person@example.com"]},
            )

        mock_schedule.assert_called_once_with(self.team.id)
        mock_schedule.reset_mock()

        with self.captureOnCommitCallbacks(execute=True):
            api.update_account(
                account,
                properties={"email_domains": ["example.com"]},
                allow_matching_updates=True,
            )

        mock_schedule.assert_called_once_with(self.team.id)

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
