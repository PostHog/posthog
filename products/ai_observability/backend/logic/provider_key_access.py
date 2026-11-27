from collections.abc import Iterable
from uuid import UUID

from products.ai_observability.backend.models.provider_keys import LLMProviderKey
from products.authorization.backend.facade import api as authorization
from products.authorization.backend.facade.contracts import CheckRequest, Resource, Subject
from products.authorization.backend.facade.enums import Action

PIN_KEY_MESSAGE = "You can use a key you added or one a project admin added."


def _project_admins(team_id: int, user_ids: Iterable[int]) -> set[int]:
    ids = list(dict.fromkeys(user_ids))
    allowed = authorization.check(
        [CheckRequest(resource=Resource.project(team_id), action=Action.EDIT, subject=Subject(user_id=i)) for i in ids]
    )
    return {user_id for user_id, ok in zip(ids, allowed) if ok}


def usable_provider_key_ids(team_id: int, keys: Iterable[LLMProviderKey], user_id: int | None) -> set[UUID]:
    """Keys this person may pin to a judge or spend in the playground.

    A key a project admin added is shared with the project. A member's key may bill their own provider
    account, so only they and project admins use it. A key whose creator was deleted counts as shared.
    """
    keys = list(keys)
    creators = {key.created_by_id for key in keys if key.created_by_id is not None and key.created_by_id != user_id}
    if not creators:
        return {key.id for key in keys}
    admins = _project_admins(team_id, [*creators, *([user_id] if user_id is not None else [])])
    if user_id is not None and user_id in admins:
        return {key.id for key in keys}
    return {key.id for key in keys if key.created_by_id is None or key.created_by_id in admins | {user_id}}


def can_use_provider_key(key: LLMProviderKey, user_id: int | None) -> bool:
    return key.id in usable_provider_key_ids(key.team_id, [key], user_id)
