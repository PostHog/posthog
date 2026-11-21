from django.db import transaction

from posthog.dataclasses import frozen
from posthog.models import Team, User
from posthog.models.activity_logging.activity_log import Change, Detail, log_activity
from posthog.models.utils import generate_random_token, mask_key_value

from products.conversations.backend.models import SigningSecret


@frozen
class SigningSecretRetirement:
    """What retiring a leaked token did to the team's signing secret row."""

    replaced: bool
    grace_window_ended: bool


def log_signing_secret_change(team: Team, changes: list[Change], *, user: User | None, was_impersonated: bool) -> None:
    """Audit write shared by every signing secret change (rotate, expire, leak
    retirement), so all entries carry the same scope and fields."""
    log_activity(
        organization_id=team.organization_id,
        team_id=team.id,
        user=user,
        was_impersonated=was_impersonated,
        scope="Team",
        item_id=team.id,
        activity="updated",
        detail=Detail(name=str(team.name), changes=changes),
    )


def retire_leaked_signing_secret(team_id: int, token: str) -> SigningSecretRetirement:
    """Replace the widget identity verification secret when it still carries a leaked
    legacy team token (#63111).

    Leak revocation deletes the token's PSAK mirror row, but a signing secret row holding
    the same value would keep verifying identity hashes signed with the leaked token.
    Mint a fresh secret with no grace window, so verification fails closed until an admin
    reads the new value from Conversations settings. Returns whether the active secret
    was replaced, and whether a rotation grace window ended because the previous secret
    held the token.
    """
    with transaction.atomic():
        row = SigningSecret.objects.for_team(team_id).select_related("team").select_for_update(of=("self",)).first()
        if row is None:
            return SigningSecretRetirement(replaced=False, grace_window_ended=False)
        changes = []
        update_fields = []
        replaced = False
        grace_window_ended = False
        if row.secret == token:
            row.secret = generate_random_token()
            row.rotated_independently = True
            update_fields += ["secret", "rotated_independently"]
            changes.append(
                Change(
                    type="Team",
                    action="changed",
                    field="conversations_signing_secret",
                    before=mask_key_value(token),
                    after=mask_key_value(row.secret),
                )
            )
            replaced = True
        if row.previous_secret == token:
            # An expired previous secret is still cleared, but the email must not claim a
            # grace window ended when the widget already rejected the value.
            grace_window_ended = row.previous_secret_active
            row.previous_secret = None
            row.previous_secret_rotated_at = None
            update_fields += ["previous_secret", "previous_secret_rotated_at"]
            changes.append(
                Change(
                    type="Team",
                    action="deleted",
                    field="conversations_signing_secret_previous",
                    before=mask_key_value(token),
                    after=None,
                )
            )
        if not update_fields:
            return SigningSecretRetirement(replaced=False, grace_window_ended=False)
        row.save(update_fields=update_fields)
        # user=None: the change is system-initiated by leak revocation, and the admin who
        # later finds a new secret needs this trail, same as the rotate endpoint writes.
        log_signing_secret_change(row.team, changes, user=None, was_impersonated=False)
        return SigningSecretRetirement(replaced=replaced, grace_window_ended=grace_window_ended)
