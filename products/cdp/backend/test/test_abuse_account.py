from datetime import timedelta

from django.test import SimpleTestCase

from parameterized import parameterized

from products.cdp.backend.abuse.account import Account, AccountCutoffs, AccountTier

DAY = timedelta(days=1)
SECOND = timedelta(seconds=1)


def account(age: timedelta, has_active_subscription: bool | None, member_count: int = 1) -> Account:
    return Account(
        age=age, has_active_subscription=has_active_subscription, member_count=member_count, cdp_trust_score=None
    )


class TestAccountTier(SimpleTestCase):
    @parameterized.expand(
        [
            ("paying_just_over_30_days", account(30 * DAY + SECOND, True), AccountTier.ESTABLISHED),
            ("paying_exactly_30_days", account(30 * DAY, True), AccountTier.STANDARD),
            ("paying_with_many_members", account(400 * DAY, True, member_count=50), AccountTier.ESTABLISHED),
            ("old_free_account", account(400 * DAY, False), AccountTier.STANDARD),
            ("old_account_billing_never_synced", account(400 * DAY, None), AccountTier.STANDARD),
            ("free_just_under_14_days", account(14 * DAY - SECOND, False), AccountTier.NEW),
            ("free_exactly_14_days", account(14 * DAY, False), AccountTier.STANDARD),
            ("free_young_at_the_member_limit", account(DAY, False, member_count=2), AccountTier.NEW),
            ("free_young_over_the_member_limit", account(DAY, False, member_count=3), AccountTier.STANDARD),
            ("young_account_billing_never_synced", account(DAY, None), AccountTier.STANDARD),
            ("young_paying_account", account(DAY, True), AccountTier.STANDARD),
        ]
    )
    def test_default_cutoffs(self, _name: str, subject: Account, expected: AccountTier) -> None:
        assert subject.tier(AccountCutoffs()) == expected

    @parameterized.expand(
        [
            (
                "shorter_established_age",
                account(8 * DAY, True),
                AccountCutoffs(established_min_age_days=7),
                AccountTier.ESTABLISHED,
            ),
            ("longer_new_age", account(20 * DAY, False), AccountCutoffs(new_max_age_days=21), AccountTier.NEW),
            (
                "higher_member_limit",
                account(DAY, False, member_count=5),
                AccountCutoffs(new_max_members=5),
                AccountTier.NEW,
            ),
        ]
    )
    def test_cutoffs_move_the_boundaries(
        self, _name: str, subject: Account, cutoffs: AccountCutoffs, expected: AccountTier
    ) -> None:
        assert subject.tier(AccountCutoffs()) == AccountTier.STANDARD
        assert subject.tier(cutoffs) == expected
