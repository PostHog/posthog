"""The account behind a hog function, which weighs how far a model score is trusted.

Pure: the shadow task loads the account, so the save path runs no extra query.
"""

from datetime import timedelta
from enum import StrEnum

from posthog.dataclasses import frozen

_MAX_AGE_DAYS = 100 * 365


class AccountTier(StrEnum):
    # A long-standing account that billing reports as subscribed. Billing counts an active trial as subscribed.
    ESTABLISHED = "established"
    # Fresh, free and small: the shape abuse takes.
    NEW = "new"
    STANDARD = "standard"


@frozen
class AccountCutoffs:
    established_min_age_days: int = 30
    new_max_age_days: int = 14
    new_max_members: int = 2

    def __post_init__(self) -> None:
        # A bound well inside what timedelta holds, so a payload typo falls back to the defaults instead of failing
        # the verdict.
        if not 0 <= self.established_min_age_days <= _MAX_AGE_DAYS or not 0 <= self.new_max_age_days <= _MAX_AGE_DAYS:
            raise ValueError(f"age cutoffs are days from 0 to {_MAX_AGE_DAYS}")
        if self.new_max_members < 0:
            raise ValueError("the member limit is not negative")


@frozen
class Account:
    age: timedelta
    # Synced by billing, and true during an active trial too. None means billing never synced the organization.
    has_active_subscription: bool | None
    member_count: int
    # Billing's trust level for CDP usage (0 none, 3 low, 7 medium, 10 high). Reported only, never decides the tier.
    cdp_trust_score: int | None

    def tier(self, cutoffs: AccountCutoffs) -> AccountTier:
        if self.has_active_subscription is True and self.age > timedelta(days=cutoffs.established_min_age_days):
            return AccountTier.ESTABLISHED
        if (
            self.has_active_subscription is False
            and self.age < timedelta(days=cutoffs.new_max_age_days)
            and self.member_count <= cutoffs.new_max_members
        ):
            return AccountTier.NEW
        return AccountTier.STANDARD
