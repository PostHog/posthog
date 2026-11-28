from collections.abc import Iterable
from uuid import UUID

from products.ai_observability.backend.models.provider_keys import LLMProviderKey
from products.authorization.backend.facade import api as authorization
from products.authorization.backend.facade.contracts import Resource, Subject
from products.authorization.backend.facade.enums import Action

PIN_KEY_MESSAGE = "You can use a key shared with the project or one you added."


def is_project_admin(team_id: int, user_id: int) -> bool:
    return authorization.check(resource=Resource.project(team_id), action=Action.EDIT, subject=Subject(user_id=user_id))


def usable_provider_key_ids(team_id: int, keys: Iterable[LLMProviderKey], user_id: int | None) -> set[UUID]:
    """Keys this person may pin to a judge or spend in the playground: shared keys, their own, and every key
    for a project admin."""
    keys = list(keys)
    usable = {key.id for key in keys if key.shared or (user_id is not None and key.created_by_id == user_id)}
    if len(usable) < len(keys) and user_id is not None and is_project_admin(team_id, user_id):
        return {key.id for key in keys}
    return usable


def can_use_provider_key(key: LLMProviderKey, user_id: int | None) -> bool:
    return key.id in usable_provider_key_ids(key.team_id, [key], user_id)
