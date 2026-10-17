import html
import hashlib

AVATAR_DISPLAY_PX = 40


def gravatar_url(email: str) -> str:
    # d=mp returns a neutral placeholder instead of a 404, so the image never shows as broken in a mail client.
    digest = hashlib.md5(email.strip().lower().encode(), usedforsecurity=False).hexdigest()
    return f"https://www.gravatar.com/avatar/{digest}?s={AVATAR_DISPLAY_PX * 2}&d=mp"


def agent_signature_html(text: str, email: str, include_profile_picture: bool) -> str:
    text_html = "<br>".join(html.escape(line) for line in text.splitlines())
    text_cell = f'<td style="vertical-align:middle;font-size:14px;line-height:1.4;">{text_html}</td>'
    picture_cell = ""
    if include_profile_picture:
        picture_cell = (
            '<td style="padding-right:12px;vertical-align:middle;">'
            f'<img src="{html.escape(gravatar_url(email))}" width="{AVATAR_DISPLAY_PX}" height="{AVATAR_DISPLAY_PX}" '
            'alt="" style="display:block;border-radius:50%;">'
            "</td>"
        )
    # Table layout because Outlook ignores flexbox and most CSS positioning.
    return (
        '<table role="presentation" cellpadding="0" cellspacing="0" border="0" style="margin-top:16px;">'
        f"<tr>{picture_cell}{text_cell}</tr>"
        "</table>"
    )


def agent_signature_text(text: str) -> str:
    return f"\n\n-- \n{text}"
