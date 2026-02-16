from urllib.parse import parse_qsl, urlencode, urljoin, urlparse, urlunparse

from django.conf import settings
from django.core import signing
from django.http import HttpRequest, HttpResponse, HttpResponseRedirect, JsonResponse
from django.views.decorators.csrf import csrf_exempt

import requests
from loginas.utils import is_impersonated_session
from rest_framework.permissions import IsAuthenticated
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView

from posthog.models.instance_setting import get_instance_settings
from posthog.models.organization import OrganizationMembership
from posthog.models.team.team import Team
from posthog.models.user import User

STATE_SALT = "conversations.supporthog.slack.oauth"
STATE_MAX_AGE_SECONDS = 10 * 60
SUPPORTHOG_SLACK_SCOPE = ",".join(
    [
        "channels:history",
        "channels:read",
        "chat:write",
        "groups:history",
        "groups:read",
        "reactions:read",
        "users:read",
    ]
)


def _append_query(url: str, params: dict[str, str]) -> str:
    parsed = urlparse(url)
    current = dict(parse_qsl(parsed.query, keep_blank_values=True))
    current.update(params)
    return urlunparse(parsed._replace(query=urlencode(current)))


def _get_callback_url() -> str:
    return urljoin(settings.SITE_URL.rstrip("/") + "/", "api/conversations/v1/slack/callback")


def _safe_next_path(team_id: int, next_path: str | None) -> str:
    default_path = f"/project/{team_id}/settings/support"
    if not next_path:
        return default_path
    if not next_path.startswith("/") or next_path.startswith("//"):
        return default_path
    return next_path


def _error_response(next_path: str | None, error_message: str, status_code: int) -> HttpResponse:
    if next_path:
        redirect_url = _append_query(
            urljoin(settings.SITE_URL.rstrip("/") + "/", next_path.lstrip("/")), {"error": error_message}
        )
        return HttpResponseRedirect(redirect_url)
    return JsonResponse({"error": error_message}, status=status_code)


class SupportSlackAuthorizeView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request: Request, *args, **kwargs) -> Response:
        support_settings = get_instance_settings(["SUPPORT_SLACK_APP_CLIENT_ID"])
        client_id = str(support_settings.get("SUPPORT_SLACK_APP_CLIENT_ID") or "")
        if not client_id:
            return Response({"error": "Support Slack OAuth client ID is not configured"}, status=503)

        user = request.user
        if not isinstance(user, User) or user.current_team is None:
            return Response({"error": "No current team selected"}, status=400)

        team_id = user.current_team.id
        user_id = getattr(user, "id", None)
        if not isinstance(user_id, int):
            return Response({"error": "Invalid user id"}, status=400)
        next_path = _safe_next_path(team_id, request.query_params.get("next"))
        state_payload = {
            "team_id": team_id,
            "user_id": user_id,
            "next": next_path,
        }
        state = signing.dumps(state_payload, salt=STATE_SALT)

        oauth_url = _append_query(
            "https://slack.com/oauth/v2/authorize",
            {
                "client_id": client_id,
                "scope": SUPPORTHOG_SLACK_SCOPE,
                "redirect_uri": _get_callback_url(),
                "state": state,
            },
        )
        return Response({"url": oauth_url})


@csrf_exempt
def support_slack_oauth_callback(request: HttpRequest) -> HttpResponse:
    state_raw = request.GET.get("state")
    code = request.GET.get("code")
    oauth_error = request.GET.get("error")

    state_data: dict
    next_path: str | None = None

    try:
        if not state_raw:
            return JsonResponse({"error": "Missing OAuth state"}, status=400)
        state_data = signing.loads(state_raw, salt=STATE_SALT, max_age=STATE_MAX_AGE_SECONDS)
        next_path = state_data.get("next")
    except signing.SignatureExpired:
        return JsonResponse({"error": "OAuth state expired"}, status=400)
    except signing.BadSignature:
        return JsonResponse({"error": "Invalid OAuth state"}, status=400)

    if oauth_error:
        return _error_response(next_path, oauth_error, 400)

    if not code:
        return _error_response(next_path, "missing_code", 400)

    support_settings = get_instance_settings(["SUPPORT_SLACK_APP_CLIENT_ID", "SUPPORT_SLACK_APP_CLIENT_SECRET"])
    client_id = str(support_settings.get("SUPPORT_SLACK_APP_CLIENT_ID") or "")
    client_secret = str(support_settings.get("SUPPORT_SLACK_APP_CLIENT_SECRET") or "")
    if not client_id or not client_secret:
        return _error_response(next_path, "support_slack_not_configured", 503)

    try:
        response = requests.post(
            "https://slack.com/api/oauth.v2.access",
            data={
                "client_id": client_id,
                "client_secret": client_secret,
                "code": code,
                "redirect_uri": _get_callback_url(),
            },
            timeout=15,
        )
        payload = response.json()
    except Exception:
        return _error_response(next_path, "oauth_exchange_failed", 502)

    if response.status_code != 200 or not payload.get("ok"):
        return _error_response(next_path, str(payload.get("error") or "oauth_exchange_failed"), 400)

    bot_token = payload.get("access_token")
    slack_team_id = payload.get("team", {}).get("id")
    user_id = state_data.get("user_id")
    team_id = state_data.get("team_id")
    if not isinstance(bot_token, str) or not bot_token:
        return _error_response(next_path, "missing_bot_token", 400)
    if not isinstance(slack_team_id, str) or not slack_team_id:
        return _error_response(next_path, "missing_slack_team_id", 400)
    if not isinstance(user_id, int) or not isinstance(team_id, int):
        return _error_response(next_path, "invalid_state_payload", 400)

    try:
        user = User.objects.get(id=user_id)
        team = Team.objects.get(id=team_id)
    except (User.DoesNotExist, Team.DoesNotExist):
        return _error_response(next_path, "team_or_user_not_found", 404)

    if not OrganizationMembership.objects.filter(user_id=user.id, organization_id=team.organization_id).exists():
        return _error_response(next_path, "forbidden_team_access", 403)

    team.save_supporthog_slack_token_and_save(
        user=user,
        is_impersonated_session=is_impersonated_session(request),
        bot_token=bot_token,
        slack_team_id=slack_team_id,
    )

    redirect_url = _append_query(
        urljoin(settings.SITE_URL.rstrip("/") + "/", _safe_next_path(team.id, next_path).lstrip("/")),
        {"supportSlackConnected": "1"},
    )
    return HttpResponseRedirect(redirect_url)
