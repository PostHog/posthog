from urllib.parse import quote

from django.utils.http import content_disposition_header


def attachment_disposition(file_name: str | None) -> str:
    """Build a Content-Disposition header that preserves the original filename.

    Without an explicit filename the browser falls back to the URL's last path
    segment — often an opaque id — so downloads lose their name and extension.

    file_name can be attacker-influenced, so strip control characters (defends
    against CR/LF header injection) before encoding.
    """
    if not file_name:
        return "attachment"

    cleaned = "".join(ch for ch in file_name if ch.isprintable()).strip()
    if not cleaned:
        return "attachment"

    if cleaned.isascii():
        return content_disposition_header(as_attachment=True, filename=cleaned) or "attachment"

    # Legacy browsers ignore the RFC 5987 parameter, so send an ASCII name beside it.
    ascii_fallback = cleaned.encode("ascii", "ignore").decode().strip() or "download"
    escaped = ascii_fallback.replace("\\", "\\\\").replace('"', '\\"')
    return f"attachment; filename=\"{escaped}\"; filename*=UTF-8''{quote(cleaned, safe='')}"
