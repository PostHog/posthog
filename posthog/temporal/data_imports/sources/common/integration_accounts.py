import dataclasses
from typing import Protocol, runtime_checkable


@dataclasses.dataclass(frozen=True)
class IntegrationAccount:
    """A selectable account/resource exposed by an OAuth integration (a Bing Ads account, a Search
    Console site, a Google Ads customer, ...).

    Every ad-platform client maps its API response onto this single shape, so one frontend selector
    and one endpoint serializer work for all of them. Platform-specific richness (lifecycle status,
    customer hierarchy) is flattened into ``badges`` / ``group`` here, in the client code that already
    has the context — keeping the shared frontend dumb.
    """

    value: str
    """What gets stored in the source config (numeric account id as a string, site url, etc.)."""
    display_name: str
    """Primary human-readable label."""
    is_primary: bool = False
    """Whether this belongs to the user's own/primary account context (sorted/marked first)."""
    badges: tuple[str, ...] = ()
    """Short status chips, e.g. ("Active",) or ("Pause",)."""
    group: str | None = None
    """Optional grouping label for hierarchical platforms (e.g. the owning customer/manager name)."""
    secondary_text: str | None = None
    """Extra identifier shown in parentheses and searchable, e.g. the alphanumeric account number."""


@runtime_checkable
class SupportsAccountListing(Protocol):
    def list_accounts(self) -> list[IntegrationAccount]: ...
