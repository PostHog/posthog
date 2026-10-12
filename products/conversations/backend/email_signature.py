import html
import hashlib

AVATAR_DISPLAY_PX = 40


def gravatar_url(email: str) -> str:
    # d=mp returns a neutral placeholder instead of a 404, so the image never shows as broken in a mail client.
    digest = hashlib.md5(email.strip().lower().encode(), usedforsecurity=False).hexdigest()
    return f"https://www.gravatar.com/avatar/{digest}?s={AVATAR_DISPLAY_PX * 2}&d=mp"


def agent_signature_html(name: str, email: str, company_name: str | None) -> str:
    company_line = ""
    if company_name and company_name != name:
        company_line = f'<div style="font-size:13px;color:#6b7280;">{html.escape(company_name)}</div>'
    # Table layout because Outlook ignores flexbox and most CSS positioning.
    return (
        '<table role="presentation" cellpadding="0" cellspacing="0" border="0" style="margin-top:16px;">'
        "<tr>"
        '<td style="padding-right:10px;vertical-align:middle;">'
        f'<img src="{html.escape(gravatar_url(email))}" width="{AVATAR_DISPLAY_PX}" height="{AVATAR_DISPLAY_PX}" '
        'alt="" style="display:block;border-radius:50%;">'
        "</td>"
        '<td style="vertical-align:middle;">'
        f'<div style="font-size:14px;font-weight:600;">{html.escape(name)}</div>'
        f"{company_line}"
        "</td>"
        "</tr>"
        "</table>"
    )


def agent_signature_text(name: str, company_name: str | None) -> str:
    lines = ["", "", "-- ", name]
    if company_name and company_name != name:
        lines.append(company_name)
    return "\n".join(lines)
