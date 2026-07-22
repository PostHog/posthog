"""Recipient-list helpers for outbound conversation emails."""

from collections.abc import Iterable

from django.core.exceptions import ValidationError
from django.core.validators import validate_email

# A reply can copy in a few extra people (a colleague, the customer's teammate),
# but cap it so a malformed or abusive payload can't fan one reply out to an
# unbounded recipient list.
MAX_EXTRA_RECIPIENTS = 20


def normalize_recipients(values: Iterable[str] | None, *, exclude: Iterable[str] = ()) -> list[str]:
    """Validate, de-duplicate, and clean a list of email addresses.

    Matching for de-duplication and against ``exclude`` (so the primary recipient
    is never also Cc'd/Bcc'd) is case-insensitive, but the original casing is kept
    in the returned list. Invalid addresses are dropped rather than raising, so a
    single bad entry can't block an otherwise-deliverable reply.
    """
    if not values:
        return []

    excluded_lower = {addr.strip().lower() for addr in exclude if addr and addr.strip()}
    seen: set[str] = set()
    result: list[str] = []
    for raw in values:
        if not isinstance(raw, str):
            continue
        addr = raw.strip()
        if not addr:
            continue
        lowered = addr.lower()
        if lowered in excluded_lower or lowered in seen:
            continue
        try:
            validate_email(addr)
        except ValidationError:
            continue
        seen.add(lowered)
        result.append(addr)
        if len(result) >= MAX_EXTRA_RECIPIENTS:
            break
    return result
