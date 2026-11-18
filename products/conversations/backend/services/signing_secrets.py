from django.db import transaction

from posthog.models.utils import generate_random_token

from products.conversations.backend.models import SigningSecret


def retire_leaked_signing_secret(team_id: int, token: str) -> bool:
    """Replace the widget identity verification secret when it still carries a leaked
    legacy team token (#63111).

    Leak revocation deletes the token's PSAK mirror row, but a signing secret row holding
    the same value would keep verifying identity hashes signed with the leaked token.
    Mint a fresh secret with no grace window, so verification fails closed until an admin
    reads the new value from Conversations settings. Returns whether anything changed.
    """
    with transaction.atomic():
        row = SigningSecret.objects.for_team(team_id).select_for_update().first()
        if row is None:
            return False
        update_fields = []
        if row.secret == token:
            row.secret = generate_random_token()
            row.rotated_independently = True
            update_fields += ["secret", "rotated_independently"]
        if row.previous_secret == token:
            row.previous_secret = None
            row.previous_secret_rotated_at = None
            update_fields += ["previous_secret", "previous_secret_rotated_at"]
        if not update_fields:
            return False
        row.save(update_fields=update_fields)
        return True
