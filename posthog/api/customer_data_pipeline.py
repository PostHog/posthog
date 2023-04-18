# The customer data pipeline API is actually defined in the `cdp/` directory,
# and is a separate process. The API here is just a proxy to that process. We
# piggy back on the existing API authentication, generate a JWT token including
# claims for the `userId` and the `projectIds` that the user has access to, and
# then pass that token to the CDP processes HTTP API as a bearer token.
#
# Note that while this is in the customer data pipeline file, it is not
# specific to the customer data pipeline. It is a generic proxy to any
# process that requires authentication, with JWT tokens used for auth on the
# other side.
#
# An improvement on this proxy method would be to use have the JWT token
# validated before the request hits any application code, which would enable
# e.g. the frontend simply to send a JWT token for authn/authz. This might be
# e.g. NGINX or some other proxy in front of the application.


from typing import TypeGuard
from django.http import HttpRequest, HttpResponse
import jwt
import requests

from django.conf import settings
from posthog.models.user import User


class HttpAuthenticatedRequest(HttpRequest):
    """
    A request that has been authenticated by the API. Use to ensure we get the
    right typing on `user`.
    """

    user: User


def request_is_authenticated(request: HttpRequest) -> TypeGuard[HttpAuthenticatedRequest]:
    """
    Check if the request has been authenticated by the API.
    """
    return hasattr(request, "user") and request.user.is_authenticated


def proxy_request_with_jwt_token(request: HttpRequest, **kwargs) -> HttpResponse:
    """
    Proxy a request to the CDP process, adding a JWT token to the request
    headers.
    """
    # Use a type guard to ensure that the request has been authenticated
    # and that we can access the user object on the request.
    if not request_is_authenticated(request):
        return HttpResponse("Request is not authenticated", status=401)

    # Generate a JWT token with the user ID and project IDs
    user = request.user
    token = jwt.encode(
        {
            "userId": user.pk,
            "projectIds": list(user.teams.values_list("pk", flat=True)),
        },
        settings.SECRET_KEY,  # This secret must be shared with the CDP process.
        algorithm="HS256",
    )

    # Proxy the request to the CDP process
    assert request.method

    response = requests.request(
        request.method,
        f"{settings.CDP_API_URL}{request.path}",
        headers={"Authorization": f"Bearer {token}"},
        data=request.body,
    )

    # Return the response from the CDP process
    return HttpResponse(
        response.content,
        status=response.status_code,
        content_type=response.headers["Content-Type"],
    )
