from ipaddress import ip_address
from urllib.parse import urlsplit

from django.conf import settings


def require_local_development() -> None:
    """Fail closed before a local demo tool touches project data or storage."""
    if not (settings.DEBUG or settings.TEST) or settings.CLOUD_DEPLOYMENT:
        raise ValueError("This tool is only available in local development")
    try:
        url = urlsplit(settings.SITE_URL)
        host = (url.hostname or "").lower().rstrip(".")
        local = (
            url.scheme in {"http", "https"}
            and url.username is None
            and url.password is None
            and not url.query
            and not url.fragment
            and url.path in {"", "/"}
            and (url.port is None or url.port > 0)
            and (host == "localhost" or ip_address(host).is_loopback)
        )
    except ValueError:
        local = False
    if not local:
        raise ValueError("This tool requires a loopback SITE_URL for local development")
