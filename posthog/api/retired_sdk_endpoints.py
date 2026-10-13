from django.http import HttpRequest, HttpResponse, JsonResponse
from django.views.decorators.csrf import csrf_exempt

from posthog.utils_cors import cors_response


@csrf_exempt
def product_tours(request: HttpRequest) -> HttpResponse:
    # Released posthog-js versions still fetch this path. An empty list lets them cache "no tours"
    # instead of retrying on an error.
    if request.method == "OPTIONS":
        return cors_response(request, HttpResponse(""))
    return cors_response(request, JsonResponse({"product_tours": []}))
