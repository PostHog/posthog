from django.http import HttpRequest, HttpResponse, JsonResponse
from django.shortcuts import render

import jwt

from posthog.models import User
from posthog.tasks.email import unsubscribe_from_notification_using_token

from products.exports.backend.models.subscription import unsubscribe_using_token


def unsubscribe(request: HttpRequest):
    token = request.GET.get("token")
    if not token:
        return JsonResponse({"success": False})

    try:
        unsubscribe_using_token(token)
    except jwt.DecodeError:
        return JsonResponse({"success": False})

    return JsonResponse({"success": True})


def notification_unsubscribe(request: HttpRequest) -> HttpResponse:
    """Public, no-login-required landing page for the one-click unsubscribe link in
    system notification emails (e.g. the data warehouse sync failure digest)."""
    token = request.GET.get("token")
    if not token:
        return render(request, "notification_unsubscribe.html", {"success": False}, status=400)

    try:
        unsubscribe_from_notification_using_token(token)
    except (jwt.PyJWTError, User.DoesNotExist):
        return render(request, "notification_unsubscribe.html", {"success": False}, status=400)

    return render(request, "notification_unsubscribe.html", {"success": True})
