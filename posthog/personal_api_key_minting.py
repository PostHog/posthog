import uuid
from collections.abc import Sequence
from dataclasses import field

from posthog.accessible_teams import AccessibleTeams, CredentialScopeDenied
from posthog.dataclasses import frozen
from posthog.models import OrganizationMembership, PersonalAPIKey, User
from posthog.models.utils import generate_random_token_personal, hash_key_value, mask_key_value


@frozen
class MintedPersonalAPIKey:
    key: PersonalAPIKey
    value: str = field(repr=False)


def mint_personal_api_key(
    owner: User,
    *,
    label: str,
    scopes: Sequence[str],
    teams: AccessibleTeams,
    organization_ids: Sequence[str] = (),
    description: str | None = None,
) -> MintedPersonalAPIKey:
    """Insert a personal API key and return it with its raw value.

    This is the only code that creates a personal API key (the `personal-api-key-created-outside-mint`
    semgrep rule enforces it), so the team scope of every key comes from an `AccessibleTeams` that
    was checked for the key's owner.
    """
    if teams.user_id != owner.pk:
        raise CredentialScopeDenied("The team scope was checked for a different user.")
    _check_organization_scope(owner, organization_ids)

    value = generate_random_token_personal()
    key = PersonalAPIKey.objects.create(
        user=owner,
        label=label,
        description=description,
        secure_value=hash_key_value(value),
        mask_value=mask_key_value(value),
        scopes=list(scopes),
        scoped_teams=list(teams.team_ids or []),
        scoped_organizations=list(organization_ids),
    )
    return MintedPersonalAPIKey(key=key, value=value)


def _check_organization_scope(owner: User, organization_ids: Sequence[str]) -> None:
    try:
        requested = {uuid.UUID(str(organization_id)) for organization_id in organization_ids}
    except ValueError:
        raise CredentialScopeDenied("One or more organization ids are not valid.") from None
    if not requested:
        return

    member_of = set(
        OrganizationMembership.objects.filter(user=owner, organization_id__in=requested).values_list(
            "organization_id", flat=True
        )
    )
    if not requested <= member_of:
        raise CredentialScopeDenied("The owner is not a member of one or more organizations.")
