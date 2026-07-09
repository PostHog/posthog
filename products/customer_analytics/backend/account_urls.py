from urllib.parse import quote

# Project-relative base path to the Customer analytics accounts list. In-app navigation adds the
# project prefix via the router; callers that need an absolute URL (e.g. agent context) prepend it.
ACCOUNTS_LIST_PATH = "/customer_analytics/accounts"


def build_account_deeplink(*, account_id: str, tab: str | None = None) -> str:
    """Build a deep link that opens a specific account in the Customer analytics accounts list —
    filtered to it, expanded, and (optionally) on a given tab.

    Returns the project-relative path `/customer_analytics/accounts/<id>[/<tab>]`. The accounts list
    reads these route params (see the `:accountId/:tab` patterns in `customer_analytics/manifest.tsx`),
    filters the list to the account by id, expands it, and opens `tab` (an account expansion tab such
    as "usage"; omit it for the default tab).

    This is the single source of truth for the Python side of the deep-link format — keep it in sync
    with the route rather than constructing the path elsewhere.
    """
    path = f"{ACCOUNTS_LIST_PATH}/{quote(str(account_id), safe='')}"
    if tab:
        path = f"{path}/{quote(tab, safe='')}"
    return path
