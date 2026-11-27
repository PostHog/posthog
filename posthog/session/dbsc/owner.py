from django.http import HttpRequest

from loginas.utils import is_impersonated_session

from posthog.helpers.impersonation import get_original_user_from_session
from posthog.models import User
from posthog.session.dbsc.binding import Binding
from posthog.session.dbsc.protocol import parse_sf_string
from posthog.session.dbsc.rollout import Mode, mode_for

_PLATFORM_HINT_HEADER = "Sec-CH-UA-Platform"
_KNOWN_PLATFORMS = frozenset({"Android", "Chrome OS", "Linux", "macOS", "Windows"})
# Chrome's macOS rollout leaves PersistDeviceBoundSessions off, so a restart drops the browser's session
# and its next request looks the same as a stolen cookie.
_SHADOW_ONLY_PLATFORMS = frozenset({"macOS"})


def client_platform(request: HttpRequest) -> str | None:
    hint = parse_sf_string(request.headers.get(_PLATFORM_HINT_HEADER))
    if hint in _KNOWN_PLATFORMS:
        return hint
    user_agent = request.headers.get("User-Agent", "")
    if "Macintosh" in user_agent:
        return "macOS"
    if "Windows NT" in user_agent:
        return "Windows"
    return None


def binding_owner(request: HttpRequest) -> User | None:
    """During impersonation the session carries the staff member's binding, so their rollout variant applies."""
    if is_impersonated_session(request):
        return get_original_user_from_session(request)
    return request.user if isinstance(request.user, User) else None


def binding_mode(request: HttpRequest, binding: Binding) -> Mode:
    owner = binding_owner(request)
    mode = mode_for(owner) if owner is not None else Mode.OFF
    if mode == Mode.ENFORCE and binding.platform in _SHADOW_ONLY_PLATFORMS:
        return Mode.SHADOW
    return mode
