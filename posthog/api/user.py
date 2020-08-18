import json
import os
import secrets
import urllib.parse

import posthoganalytics
import requests
from django.conf import settings
from django.contrib.auth import update_session_auth_hash
from django.contrib.auth.password_validation import validate_password
from django.core.exceptions import ValidationError
from django.http import HttpResponse, JsonResponse, request
from django.shortcuts import redirect
from django.views.decorators.http import require_http_methods
from rest_framework import exceptions, serializers

from posthog.models import Event, User
from posthog.utils import PersonalAPIKeyAuthentication
from version import VERSION


def authenticateSecondarily(request: request.HttpRequest) -> None:
    if request.user.is_authenticated:
        return
    auth_result = PersonalAPIKeyAuthentication().authenticate(request)
    if isinstance(auth_result, tuple) and isinstance(auth_result[0], User):
        request.user = auth_result[0]
    else:
        raise exceptions.AuthenticationFailed("Authentication credentials were not provided.")


# TODO: remake these endpoints with DRF!
def user(request):
    try:
        authenticateSecondarily(request)
    except exceptions.AuthenticationFailed as e:
        return JsonResponse({"detail": e.detail}, status=401)

    team = request.user.team

    if request.method == "PATCH":
        data = json.loads(request.body)

        if "team" in data:
            team.app_urls = data["team"].get("app_urls", team.app_urls)
            team.opt_out_capture = data["team"].get("opt_out_capture", team.opt_out_capture)
            team.slack_incoming_webhook = data["team"].get("slack_incoming_webhook", team.slack_incoming_webhook)
            team.anonymize_ips = data["team"].get("anonymize_ips", team.anonymize_ips)
            team.completed_snippet_onboarding = data["team"].get(
                "completed_snippet_onboarding", team.completed_snippet_onboarding
            )
            team.save()

        if "user" in data:
            request.user.email_opt_in = data["user"].get("email_opt_in", request.user.email_opt_in)
            request.user.anonymize_data = data["user"].get("anonymize_data", request.user.anonymize_data)
            request.user.toolbar_mode = data["user"].get("toolbar_mode", request.user.toolbar_mode)
            posthoganalytics.identify(
                request.user.distinct_id,
                {
                    "email_opt_in": request.user.email_opt_in,
                    "anonymize_data": request.user.anonymize_data,
                    "email": request.user.email if not request.user.anonymize_data else None,
                    "is_signed_up": True,
                },
            )
            request.user.save()

    return JsonResponse(
        {
            "id": request.user.pk,
            "distinct_id": request.user.distinct_id,
            "name": request.user.first_name,
            "email": request.user.email,
            "has_events": Event.objects.filter(team=team).exists(),
            "email_opt_in": request.user.email_opt_in,
            "anonymize_data": request.user.anonymize_data,
            "toolbar_mode": request.user.toolbar_mode,
            "team": {
                "app_urls": team.app_urls,
                "api_token": team.api_token,
                "signup_token": team.signup_token,
                "opt_out_capture": team.opt_out_capture,
                "anonymize_ips": team.anonymize_ips,
                "slack_incoming_webhook": team.slack_incoming_webhook,
                "event_names": team.event_names,
                "event_properties": team.event_properties,
                "event_properties_numerical": team.event_properties_numerical,
                "completed_snippet_onboarding": team.completed_snippet_onboarding,
            },
            "opt_out_capture": os.environ.get("OPT_OUT_CAPTURE"),
            "posthog_version": VERSION,
            "available_features": request.user.available_features,
            "billing_plan": request.user.billing_plan,
            "is_multi_tenancy": hasattr(settings, "MULTI_TENANCY"),
            "ee_available": request.user.ee_available,
        }
    )


def redirect_to_site(request):
    try:
        authenticateSecondarily(request)
    except exceptions.AuthenticationFailed as e:
        return JsonResponse({"detail": e.detail}, status=401)

    team = request.user.team_set.get()
    app_url = request.GET.get("appUrl") or (team.app_urls and team.app_urls[0])
    use_new_toolbar = request.user.toolbar_mode == "toolbar"

    if not app_url:
        return HttpResponse(status=404)

    request.user.temporary_token = secrets.token_urlsafe(32)
    request.user.save()
    params = {
        "action": "ph_authorize",
        "token": team.api_token,
        "temporaryToken": request.user.temporary_token,
        "actionId": request.GET.get("actionId"),
        "userIntent": request.GET.get("userIntent"),
    }

    if settings.JS_URL:
        params["jsURL"] = settings.JS_URL

    if use_new_toolbar:
        params["action"] = "ph_authorize"
        params["toolbarVersion"] = "toolbar"

    if not settings.TEST and not os.environ.get("OPT_OUT_CAPTURE"):
        params["instrument"] = True
        params["userEmail"] = request.user.email
        params["distinctId"] = request.user.distinct_id

    state = urllib.parse.quote(json.dumps(params))

    if use_new_toolbar:
        return redirect("{}#__posthog={}".format(app_url, state))
    else:
        return redirect("{}#state={}".format(app_url, state))


@require_http_methods(["PATCH"])
def change_password(request):
    """Change the password of a regular User."""
    try:
        authenticateSecondarily(request)
    except exceptions.AuthenticationFailed as e:
        return JsonResponse({"detail": e.detail}, status=401)

    try:
        body = json.loads(request.body)
    except (TypeError, json.decoder.JSONDecodeError):
        return JsonResponse({"error": "Cannot parse request body"}, status=400)

    old_password = body.get("oldPassword")
    new_password = body.get("newPassword")

    if not old_password or not new_password:
        return JsonResponse({"error": "Missing payload"}, status=400)

    if not request.user.check_password(old_password):
        return JsonResponse({"error": "Incorrect old password"}, status=400)

    try:
        validate_password(new_password, request.user)
    except ValidationError as err:
        return JsonResponse({"error": err.messages[0]}, status=400)

    request.user.set_password(new_password)
    request.user.save()
    update_session_auth_hash(request, request.user)

    return JsonResponse({})


@require_http_methods(["POST"])
def test_slack_webhook(request):
    """Change the password of a regular User."""
    try:
        authenticateSecondarily(request)
    except exceptions.AuthenticationFailed as e:
        return JsonResponse({"detail": e.detail}, status=401)

    try:
        body = json.loads(request.body)
    except (TypeError, json.decoder.JSONDecodeError):
        return JsonResponse({"error": "Cannot parse request body"}, status=400)

    webhook = body.get("webhook")

    if not webhook:
        return JsonResponse({"error": "no webhook URL"})
    message = {"text": "Greetings from PostHog!"}
    try:
        response = requests.post(webhook, verify=False, json=message)

        if response.ok:
            return JsonResponse({"success": True})
        else:
            return JsonResponse({"error": response.text})
    except:
        return JsonResponse({"error": "invalid webhook URL"})


class UserSerializer(serializers.ModelSerializer):
    class Meta:
        model = User
        fields = ["id", "distinct_id", "first_name", "email"]
