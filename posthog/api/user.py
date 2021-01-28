import json
import os
import secrets
import urllib.parse
from typing import Optional, cast

import requests
from django.conf import settings
from django.contrib.auth import update_session_auth_hash
from django.contrib.auth.password_validation import validate_password
from django.core.exceptions import ObjectDoesNotExist, ValidationError
from django.http import HttpResponse, JsonResponse
from django.shortcuts import redirect
from django.views.decorators.http import require_http_methods
from loginas.utils import is_impersonated_session
from rest_framework import serializers

from posthog.auth import authenticate_secondarily
from posthog.ee import is_ee_enabled
from posthog.email import is_email_available
from posthog.models import Team, User
from posthog.models.organization import Organization
from posthog.plugins import can_configure_plugins_via_api, can_install_plugins_via_api, reload_plugins_on_workers
from posthog.tasks import user_identify
from posthog.version import VERSION


class UserSerializer(serializers.ModelSerializer):
    class Meta:
        model = User
        fields = ["id", "distinct_id", "first_name", "email"]


# TODO: remake these endpoints with DRF!
@authenticate_secondarily
def user(request):
    organization: Optional[Organization] = request.user.organization
    organizations = list(request.user.organizations.order_by("-created_at").values("name", "id"))
    team: Optional[Team] = request.user.team
    teams = list(request.user.teams.order_by("-created_at").values("name", "id"))
    user = cast(User, request.user)

    if request.method == "PATCH":
        data = json.loads(request.body)

        if team is not None and "team" in data:
            team.app_urls = data["team"].get("app_urls", team.app_urls)
            team.opt_out_capture = data["team"].get("opt_out_capture", team.opt_out_capture)
            team.slack_incoming_webhook = data["team"].get("slack_incoming_webhook", team.slack_incoming_webhook)
            team.anonymize_ips = data["team"].get("anonymize_ips", team.anonymize_ips)
            team.session_recording_opt_in = data["team"].get("session_recording_opt_in", team.session_recording_opt_in)
            team.session_recording_retention_period_days = data["team"].get(
                "session_recording_retention_period_days", team.session_recording_retention_period_days
            )
            if data["team"].get("plugins_opt_in") is not None:
                reload_plugins_on_workers()
            team.plugins_opt_in = data["team"].get("plugins_opt_in", team.plugins_opt_in)
            team.completed_snippet_onboarding = data["team"].get(
                "completed_snippet_onboarding", team.completed_snippet_onboarding,
            )
            team.save()

        if "user" in data:
            try:
                user.current_organization = user.organizations.get(id=data["user"]["current_organization_id"])
                assert user.organization is not None, "Organization should have been just set"
                user.current_team = user.organization.teams.first()
            except (KeyError, ValueError):
                pass
            except ObjectDoesNotExist:
                return JsonResponse({"detail": "Organization not found for user."}, status=404)
            except KeyError:
                pass
            except ObjectDoesNotExist:
                return JsonResponse({"detail": "Organization not found for user."}, status=404)
            if user.organization is not None:
                try:
                    user.current_team = user.organization.teams.get(id=int(data["user"]["current_team_id"]))
                except (KeyError, TypeError):
                    pass
                except ValueError:
                    return JsonResponse({"detail": "Team ID must be an integer."}, status=400)
                except ObjectDoesNotExist:
                    return JsonResponse({"detail": "Team not found for user's current organization."}, status=404)
            user.email_opt_in = data["user"].get("email_opt_in", user.email_opt_in)
            user.anonymize_data = data["user"].get("anonymize_data", user.anonymize_data)
            user.toolbar_mode = data["user"].get("toolbar_mode", user.toolbar_mode)
            user.save()

    user_identify.identify_task.delay(user_id=user.id)

    return JsonResponse(
        {
            "id": user.pk,
            "distinct_id": user.distinct_id,
            "name": user.first_name,
            "email": user.email,
            "email_opt_in": user.email_opt_in,
            "anonymize_data": user.anonymize_data,
            "toolbar_mode": user.toolbar_mode,
            "organization": None
            if organization is None
            else {
                "id": organization.id,
                "name": organization.name,
                "billing_plan": organization.billing_plan,
                "available_features": organization.available_features,
                "created_at": organization.created_at,
                "updated_at": organization.updated_at,
                "teams": [{"id": team.id, "name": team.name} for team in organization.teams.all().only("id", "name")],
            },
            "organizations": organizations,
            "team": None
            if team is None
            else {
                "id": team.id,
                "name": team.name,
                "app_urls": team.app_urls,
                "api_token": team.api_token,
                "opt_out_capture": team.opt_out_capture,
                "anonymize_ips": team.anonymize_ips,
                "slack_incoming_webhook": team.slack_incoming_webhook,
                "event_names": team.event_names,
                "event_names_with_usage": team.event_names_with_usage
                or [{"event": event, "volume": None, "usage_count": None} for event in team.event_names],
                "event_properties": team.event_properties,
                "event_properties_numerical": team.event_properties_numerical,
                "event_properties_with_usage": team.event_properties_with_usage
                or [{"key": key, "volume": None, "usage_count": None} for key in team.event_properties],
                "completed_snippet_onboarding": team.completed_snippet_onboarding,
                "session_recording_opt_in": team.session_recording_opt_in,
                "session_recording_retention_period_days": team.session_recording_retention_period_days,
                "plugins_opt_in": team.plugins_opt_in,
                "ingested_event": team.ingested_event,
                "is_demo": team.is_demo,
            },
            "teams": teams,
            "has_password": user.has_usable_password(),
            "opt_out_capture": os.environ.get("OPT_OUT_CAPTURE"),
            "posthog_version": VERSION,
            "is_multi_tenancy": getattr(settings, "MULTI_TENANCY", False),
            "ee_available": settings.EE_AVAILABLE,
            "ee_enabled": is_ee_enabled(),
            "email_service_available": is_email_available(with_absolute_urls=True),
            "is_debug": getattr(settings, "DEBUG", False),
            "is_staff": user.is_staff,
            "is_impersonated": is_impersonated_session(request),
            "plugin_access": {
                "install": can_install_plugins_via_api(user.organization),
                "configure": can_configure_plugins_via_api(user.organization),
            },
        }
    )


@authenticate_secondarily
def redirect_to_site(request):
    team = request.user.team
    app_url = request.GET.get("appUrl") or (team.app_urls and team.app_urls[0])
    use_new_toolbar = request.user.toolbar_mode != "disabled"

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
        "toolbarVersion": "toolbar",
    }

    if settings.JS_URL:
        params["jsURL"] = settings.JS_URL

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
@authenticate_secondarily
def change_password(request):
    """Change the password of a regular User."""
    try:
        body = json.loads(request.body)
    except (TypeError, json.decoder.JSONDecodeError):
        return JsonResponse({"error": "Cannot parse request body"}, status=400)

    old_password = body.get("currentPassword")
    new_password = body.get("newPassword")

    user = cast(User, request.user)

    if user.has_usable_password():
        if not old_password or not new_password:
            return JsonResponse({"error": "Missing payload"}, status=400)

        if not user.check_password(old_password):
            return JsonResponse({"error": "Incorrect old password"}, status=400)

    try:
        validate_password(new_password, user)
    except ValidationError as err:
        return JsonResponse({"error": err.messages[0]}, status=400)

    user.set_password(new_password)
    user.save()
    update_session_auth_hash(request, user)

    return JsonResponse({})


@require_http_methods(["POST"])
@authenticate_secondarily
def test_slack_webhook(request):
    """Test webhook."""
    try:
        body = json.loads(request.body)
    except (TypeError, json.decoder.JSONDecodeError):
        return JsonResponse({"error": "Cannot parse request body"}, status=400)

    webhook = body.get("webhook")

    if not webhook:
        return JsonResponse({"error": "no webhook URL"})
    message = {"text": "_Greetings_ from PostHog!"}
    try:
        response = requests.post(webhook, verify=False, json=message)

        if response.ok:
            return JsonResponse({"success": True})
        else:
            return JsonResponse({"error": response.text})
    except:
        return JsonResponse({"error": "invalid webhook URL"})
