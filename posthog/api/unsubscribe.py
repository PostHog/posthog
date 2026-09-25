from django.http import HttpRequest, JsonResponse

import jwt

from products.exports.backend.models.subscription import Subscription, unsubscribe_using_token


def unsubscribe(request: HttpRequest):
    token = request.GET.get("token")
    if not token:
        return JsonResponse({"success": False})

    try:
        unsubscribe_using_token(token)
    except (jwt.InvalidTokenError, Subscription.DoesNotExist):
        # An unsubscribe link arrives by email, so the recipient cannot retry it. Every
        # unusable token gets the "may already be unsubscribed" page, never an error.
        return JsonResponse({"success": False})

    return JsonResponse({"success": True})
