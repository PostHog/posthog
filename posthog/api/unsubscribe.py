from django.http import HttpRequest, JsonResponse

import jwt

from products.subscriptions.backend.facade import api as subscriptions_api


def unsubscribe(request: HttpRequest):
    token = request.GET.get("token")
    if not token:
        return JsonResponse({"success": False})

    try:
        subscriptions_api.unsubscribe(token)
    except jwt.DecodeError:
        return JsonResponse({"success": False})

    return JsonResponse({"success": True})
