"""The confirmation email that proves a customer owns the address they typed into another channel.

The email carries no ticket content and no customer-supplied text. The address is unverified
when the email goes out, so anything a visitor typed into the widget must stay out of it.
"""

import secrets
from email.utils import make_msgid

# Marks the private note that records the confirmation email. The send path reads this key
# to email the fixed body below instead of the note's text.
EMAIL_CONFIRMATION_CONTEXT_KEY = "email_delivery_confirmation"


def is_email_confirmation(item_context: object) -> bool:
    return isinstance(item_context, dict) and item_context.get(EMAIL_CONFIRMATION_CONTEXT_KEY) is True


def new_confirmation_message_id(domain: str | None) -> str:
    """Message-ID for a confirmation email.

    A reply that carries this ID in its threading headers is the proof that the customer
    received the email, so the ID must not be guessable. `make_msgid` alone draws from a
    non-cryptographic generator.
    """
    token = secrets.token_hex(16)
    return make_msgid(idstring=token, domain=domain) if domain else make_msgid(idstring=token)


def confirmation_subject(ticket_number: int) -> str:
    return f"We've got your support ticket (#{ticket_number})"


def confirmation_note(recipient: str) -> str:
    return (
        f"Confirmation email sent to {recipient}. "
        "Replies on this ticket are emailed after the customer replies to that email."
    )


_CONFIRMATION_PARAGRAPHS = (
    "Hello,",
    "We've got your support ticket (#{ticket_number}). To get our replies by email, reply to this message. "
    "A short reply is enough, and you can also add more detail about the issue.",
    "If you didn't contact us, you can ignore this email.",
)


def confirmation_email_text(ticket_number: int) -> str:
    return "\n\n".join(paragraph.format(ticket_number=ticket_number) for paragraph in _CONFIRMATION_PARAGRAPHS)


def confirmation_email_html(ticket_number: int) -> str:
    return "".join(f"<p>{paragraph.format(ticket_number=ticket_number)}</p>" for paragraph in _CONFIRMATION_PARAGRAPHS)
