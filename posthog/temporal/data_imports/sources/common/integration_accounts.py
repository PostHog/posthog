import dataclasses
from typing import Protocol, runtime_checkable


@dataclasses.dataclass(frozen=True)
class IntegrationAccount:
    """A selectable account/resource an OAuth integration exposes (a Bing account, a Search Console
    site, ...). Each platform's client maps its API onto this shape so one frontend selector and one
    serializer cover all of them; platform-specific richness flattens into ``badges`` / ``group``.
    """

    value: str
    """Stored in the source config (numeric account id as a string, site url, etc.)."""
    display_name: str
    is_primary: bool = False
    """Belongs to the user's own/primary account context (sorted first)."""
    badges: tuple[str, ...] = ()
    """Status chips, e.g. ("Active",)."""
    group: str | None = None
    """Grouping for hierarchical platforms (e.g. the owning customer name)."""
    secondary_text: str | None = None
    """Extra searchable identifier shown in parentheses, e.g. the account number."""


@runtime_checkable
class SupportsAccountListing(Protocol):
    def list_accounts(self) -> list[IntegrationAccount]: ...
