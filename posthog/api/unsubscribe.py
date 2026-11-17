from django.core.exceptions import ObjectDoesNotExist
from django.http import HttpRequest, HttpResponseRedirect, JsonResponse
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_http_methods

import jwt

from products.subscriptions.backend.facade import api as subscriptions_api


# Mail clients send RFC 8058 one-click unsubscribes as a cookieless POST. Link scanners and people
# opening the List-Unsubscribe URL send a GET, which goes to the page that asks before it posts.
@csrf_exempt
@require_http_methods(["GET", "POST"])
def unsubscribe(request: HttpRequest):
    if request.method == "GET":
        return HttpResponseRedirect(f"/unsubscribe?{request.GET.urlencode()}")

    token = request.GET.get("token")
    if not token:
        return JsonResponse({"success": False})

    try:
        subscriptions_api.unsubscribe(token)
    except (jwt.InvalidTokenError, ObjectDoesNotExist):
        return JsonResponse({"success": False})

    return JsonResponse({"success": True})
