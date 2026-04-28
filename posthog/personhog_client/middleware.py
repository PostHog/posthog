from django.http import HttpRequest, HttpResponse

from posthog.personhog_client.gate import pin_personhog_decision, unpin_personhog_decision


class PersonHogGateMiddleware:
    """Pin the personhog gate decision for the lifetime of an HTTP request.

    This ensures that all personhog-routed calls within a single request
    consistently use the same backend (either all gRPC or all ORM),
    avoiding mixed-source reads during partial rollout.
    """

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request: HttpRequest) -> HttpResponse:
        pin_personhog_decision()
        try:
            return self.get_response(request)
        finally:
            unpin_personhog_decision()
