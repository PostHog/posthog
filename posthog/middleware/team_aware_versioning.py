import structlog
from django.http.request import HttpRequest
from reversion.middleware import RevisionMiddleware


class TeamAwareVersioning(RevisionMiddleware):
    def __init__(self, get_response):
        super().__init__(get_response)
        self.logger = structlog.get_logger(__name__)

    def request_creates_revision(self, request: HttpRequest):
        does_this_request_create_a_revision = super().request_creates_revision(request)
        self.logger.info(f"maybe creating revision for {request}: {does_this_request_create_a_revision}")
        return does_this_request_create_a_revision

    def __call__(self, request):
        response = self.get_response(request)
        self.logger.info(f"versioning from {request} to {response}")
        return response
