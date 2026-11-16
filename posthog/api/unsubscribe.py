from django.core.exceptions import ObjectDoesNotExist
from django.http import HttpRequest, JsonResponse
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_POST

import jwt

from products.subscriptions.backend.facade import api as subscriptions_api


# Mail clients send RFC 8058 one-click unsubscribes as a cookieless POST, and link scanners only GET.
@csrf_exempt
@require_POST
def unsubscribe(request: HttpRequest):
    token = request.GET.get("token")
    if not token:
        return JsonResponse({"success": False})

    try:
        subscriptions_api.unsubscribe(token)
    except (jwt.InvalidTokenError, ObjectDoesNotExist):
        return JsonResponse({"success": False})

    return JsonResponse({"success": True})
