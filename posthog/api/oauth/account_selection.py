"""The account chooser that `/oauth/authorize/` shows for OIDC `prompt=select_account`."""

from urllib.parse import unquote_plus, urlencode

AUTHORIZE_PATH = "/oauth/authorize/"
SELECT_ACCOUNT = "select_account"


def requests_account_selection(prompt: str | None) -> bool:
    # `none` forbids any interaction, and `login` asks for a new login rather than a choice,
    # so a request that also carries either one keeps the handling it has without the chooser.
    tokens = (prompt or "").split()
    return SELECT_ACCOUNT in tokens and not {"none", "login"} & set(tokens)


def account_selection_continue_path(query_string: str) -> str:
    """The authorize request to load after the person has chosen an account.

    The path is fixed here, so the target never comes from the request. Every parameter
    other than `prompt` keeps its raw bytes, so `state`, `redirect_uri`, `nonce` and the
    PKCE challenge reach the next request exactly as the client sent them. `prompt` keeps
    its other tokens and goes away when `select_account` was the only one.
    """
    kept: list[str] = []
    for segment in query_string.split("&"):
        if not segment:
            continue
        raw_name, _, raw_value = segment.partition("=")
        if unquote_plus(raw_name) != "prompt":
            kept.append(segment)
            continue
        remaining = [token for token in unquote_plus(raw_value).split() if token != SELECT_ACCOUNT]
        if remaining:
            kept.append(urlencode({"prompt": " ".join(remaining)}))
    query = "&".join(kept)
    return f"{AUTHORIZE_PATH}?{query}" if query else AUTHORIZE_PATH
