def start_url_from_first_url(url: str | None) -> str | None:
    """Derive a recording's `start_url` from the first page URL of the session.

    The first URL can carry authentication values in its query string, such as tokens, credentials,
    or session keys. Keep only the path so those values never reach storage or a client, including the
    MCP query response. Truncate to the model column length."""
    return url.split("?")[0][:512] if url else None
