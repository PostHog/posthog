from django.http import HttpRequest, HttpResponse
from django.shortcuts import render
from django.views.decorators.csrf import csrf_protect
from django.views.decorators.http import require_http_methods
from django.http import JsonResponse
import structlog

from posthog.models.message_preferences import RecipientIdentifier, MessageCategory, MessagePreference

logger = structlog.get_logger(__name__)


@require_http_methods(["GET"])
def preferences_page(request: HttpRequest, token: str) -> HttpResponse:
    """Render the preferences page for a given recipient token"""
    recipient, error = RecipientIdentifier.validate_preferences_token(token)

    if error:
        return render(request, "message_preferences/error.html", {"error": error}, status=400)

    # Only fetch active categories and their preferences
    categories = MessageCategory.objects.all().order_by("name")
    preferences = {pref.category_id: pref.opted_in for pref in MessagePreference.objects.filter(recipient=recipient)}

    context = {
        "recipient": recipient,
        "categories": [
            {"id": cat.id, "name": cat.name, "description": cat.description, "opted_in": preferences.get(cat.id, None)}
            for cat in categories
        ],
        "token": token,  # Need to pass this back for the update endpoint
    }

    return render(request, "message_preferences/preferences.html", context)


@csrf_protect
@require_http_methods(["POST"])
def update_preferences(request: HttpRequest) -> JsonResponse:
    """Update preferences for a recipient"""
    token = request.POST.get("token")
    if not token:
        return JsonResponse({"error": "Missing token"}, status=400)

    recipient, error = RecipientIdentifier.validate_preferences_token(token)
    if error:
        return JsonResponse({"error": error}, status=400)

    try:
        preferences = request.POST.getlist("preferences[]")
        # Convert to dict of category_id: opted_in
        updates = {}
        for pref in preferences:
            category_id, opted_in = pref.split(":")
            updates[int(category_id)] = opted_in == "true"

        # Update all preferences
        for category_id, opted_in in updates.items():
            MessagePreference.objects.update_or_create(
                recipient=recipient, category_id=category_id, defaults={"opted_in": opted_in}
            )

        logger.info(
            "message_preferences.updated", recipient_id=recipient.id, recipient_type=recipient.type, updates=updates
        )

        return JsonResponse({"success": True})

    except Exception as e:
        logger.exception(
            "message_preferences.update_failed", recipient_id=recipient.id, recipient_type=recipient.type, error=str(e)
        )
        return JsonResponse({"error": "Failed to update preferences"}, status=500)
