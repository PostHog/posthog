from __future__ import annotations

import base64
import secrets
from urllib.parse import urlencode

from django.conf import settings
from django.contrib.auth.decorators import login_required
from django.core.cache import cache
from django.http import HttpResponse, HttpResponseRedirect
from django.http.response import HttpResponseBase
from django.views.decorators.csrf import csrf_exempt

import structlog

from posthog.exceptions_capture import capture_exception
from posthog.security.outbound_proxy import external_requests

from . import STATE_CACHE_PREFIX, STATE_CACHE_TTL, TOKEN_CACHE_PREFIX, TOKEN_CACHE_TTL

logger = structlog.get_logger(__name__)


@login_required
def supabase_install(request) -> HttpResponseBase:
    state = secrets.token_urlsafe(32)
    cache.set(f"{STATE_CACHE_PREFIX}{state}", request.user.id, timeout=STATE_CACHE_TTL)

    redirect_uri = request.build_absolute_uri("/integrations/supabase/callback")
    params = {
        "client_id": settings.SUPABASE_OAUTH_CLIENT_ID,
        "redirect_uri": redirect_uri,
        "response_type": "code",
        "state": state,
    }
    authorize_url = f"{settings.SUPABASE_API_BASE_URL}/oauth/authorize?{urlencode(params)}"
    return HttpResponseRedirect(authorize_url)


@csrf_exempt
def supabase_callback(request) -> HttpResponseBase:
    code = request.GET.get("code")
    state = request.GET.get("state")

    if not code or not state:
        return HttpResponse("Missing code or state parameter", status=400)

    user_id = cache.get(f"{STATE_CACHE_PREFIX}{state}")
    if user_id is None:
        return HttpResponse("Invalid or expired state", status=400)

    cache.delete(f"{STATE_CACHE_PREFIX}{state}")

    redirect_uri = request.build_absolute_uri("/integrations/supabase/callback")
    credentials = base64.b64encode(
        f"{settings.SUPABASE_OAUTH_CLIENT_ID}:{settings.SUPABASE_OAUTH_CLIENT_SECRET}".encode()
    ).decode()

    try:
        token_response = external_requests.post(
            f"{settings.SUPABASE_API_BASE_URL}/oauth/token",
            data={
                "grant_type": "authorization_code",
                "code": code,
                "redirect_uri": redirect_uri,
            },
            headers={
                "Authorization": f"Basic {credentials}",
                "Content-Type": "application/x-www-form-urlencoded",
            },
        )
        token_response.raise_for_status()
    except Exception as e:
        logger.exception("supabase_oauth.token_exchange_failed")
        capture_exception(e)
        return HttpResponse("Failed to exchange authorization code", status=502)

    token_data = token_response.json()
    access_token = token_data.get("access_token")
    refresh_token = token_data.get("refresh_token")

    try:
        orgs_response = external_requests.get(
            f"{settings.SUPABASE_API_BASE_URL}/organizations",
            headers={"Authorization": f"Bearer {access_token}"},
        )
        orgs_response.raise_for_status()
        supabase_orgs = orgs_response.json()
    except Exception as e:
        logger.exception("supabase_oauth.orgs_fetch_failed")
        capture_exception(e)
        supabase_orgs = []

    cache.set(
        f"{TOKEN_CACHE_PREFIX}{user_id}",
        {
            "access_token": access_token,
            "refresh_token": refresh_token,
            "supabase_orgs": supabase_orgs,
        },
        timeout=TOKEN_CACHE_TTL,
    )

    return HttpResponseRedirect("/project/settings?supabase=connected")
