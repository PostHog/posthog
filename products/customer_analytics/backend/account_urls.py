import json
from urllib.parse import quote

# Project-relative path to the Customer analytics accounts list. In-app navigation adds the project
# prefix via the router; callers that need an absolute URL (e.g. agent context) prepend it themselves.
ACCOUNTS_LIST_PATH = "/customer_analytics/accounts"


def build_account_deeplink(
    *,
    account_id: str,
    external_id: str | None = None,
    name: str | None = None,
    tab: str | None = None,
) -> str:
    """Build a deep link that opens a specific account in the Customer analytics accounts list,
    expanded and (optionally) on a given tab — instead of the bare list.

    Returns the project-relative path with an `#open=` hash. The hash mirrors `AccountsOpenUrlState`
    in `accountsLogic.ts` and kea-router's encoding (compact `JSON.stringify` + percent-encoding), so
    the list consumes it on load to reveal/expand/scroll to the account. `external_id`/`name` let the
    list reveal the account when it's off-screen; `id` drives the expand and scroll. `tab` (an account
    expansion tab such as "usage") is validated client-side and falls back to the default when omitted.

    This is the single source of truth for the deep-link format — keep it in sync with
    `AccountsOpenUrlState` rather than reconstructing the hash elsewhere.
    """
    open_state: dict[str, str] = {"id": str(account_id)}
    if external_id:
        open_state["externalId"] = external_id
    if name:
        open_state["name"] = name
    if tab:
        open_state["tab"] = tab
    encoded = quote(json.dumps(open_state, separators=(",", ":")), safe="")
    return f"{ACCOUNTS_LIST_PATH}#open={encoded}"
