from __future__ import annotations

from datetime import datetime
from typing import Any, Optional, cast

from django.conf import settings
from django.http import HttpRequest

from rest_framework.request import Request

from posthog.models.activity_logging.model_activity import is_impersonated_session
from posthog.models.file_system.file_system_view_log import log_file_system_view, resolve_representation

CacheKey = tuple[int, str, str]
RequestLike = Request | HttpRequest


def _has_session_cookie(request: RequestLike) -> bool:
    try:
        cookies = request.COOKIES
    except AttributeError:
        return False

    return settings.SESSION_COOKIE_NAME in cookies and bool(cookies[settings.SESSION_COOKIE_NAME])


def log_api_file_system_view(
    request: RequestLike,
    obj: Any,
    *,
    viewed_at: Optional[datetime] = None,
    team_id: Optional[int] = None,
) -> None:
    """Log a FileSystem view if the request represents an authenticated session."""

    user = getattr(request, "user", None)
    if user is None or not getattr(user, "is_authenticated", False):
        return

    if not _has_session_cookie(request):
        return

    if is_impersonated_session(request):
        return

    resolved = resolve_representation(obj, team_id=team_id)
    if resolved is None:
        return

    resolved_team_id, representation = resolved

    logged_views = cast(Optional[set[CacheKey]], getattr(request, "_file_system_logged_views", None))
    if logged_views is None:
        logged_views = cast(set[CacheKey], set())
        request._file_system_logged_views = logged_views  # type: ignore

    cache_key: CacheKey = (resolved_team_id, representation.type, str(representation.ref))
    if cache_key in logged_views:
        return

    logged_views.add(cache_key)

    log_file_system_view(
        user=user,
        obj=representation,
        team_id=resolved_team_id,
        viewed_at=viewed_at,
    )
