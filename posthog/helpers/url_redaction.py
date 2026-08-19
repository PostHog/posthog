from urllib.parse import urlparse

HIDDEN_URL = "(hidden)"


def redact_webhook_url(url: str) -> str:
    try:
        parsed = urlparse(url)
        hostname, port = parsed.hostname, parsed.port
    except ValueError:
        return HIDDEN_URL
    if not parsed.scheme or not hostname:
        return HIDDEN_URL
    host = f"[{hostname}]" if ":" in hostname else hostname
    authority = f"{host}:{port}" if port else host
    return f"{parsed.scheme}://{authority}/…"
