from django.http import HttpRequest

from loginas.utils import is_impersonated_session

from posthog.helpers.impersonation import get_original_user_from_session
from posthog.models import User


def binding_owner(request: HttpRequest) -> User | None:
    """During impersonation the session carries the staff member's binding, so their rollout variant applies."""
    if is_impersonated_session(request):
        return get_original_user_from_session(request)
    return request.user if isinstance(request.user, User) else None
