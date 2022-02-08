from typing import Optional

import structlog
from django.http.request import HttpRequest
from reversion.middleware import RevisionMiddleware

from posthog.api.utils import get_data, get_event_ingestion_context, get_token

VERSIONING_EXCLUSIONS = ["/e/", "/s/", "/decide/"]


class TeamAwareVersioning(RevisionMiddleware):
    def __init__(self, get_response):
        super().__init__(get_response)
        self.logger = structlog.get_logger(__name__)

    def request_creates_revision(self, request: HttpRequest):
        """
        Reversion tries to create a revision for any request that isn't OPTION, GET or HEAD

        There are some URLs that can be on a deny-list since we know they are called frequently
        but never generate a version
        """
        reversion_would_create_a_revision = super().request_creates_revision(request)

        if request.path in VERSIONING_EXCLUSIONS:
            return False

        if reversion_would_create_a_revision:
            team_id = self._get_team_id_from_request(request)

            self.logger.info(
                f"[VERSIONING] maybe creating revision",
                team_id=team_id,
                reversion_would_create_a_revision=reversion_would_create_a_revision,
                request_path=request.path,
            )
            return reversion_would_create_a_revision and team_id
        else:
            return False

    def __call__(self, request):
        response = self.get_response(request)
        return response

    @staticmethod
    def _get_team_id_from_request(request) -> Optional[int]:
        try:
            data, error_response = get_data(request)
            request_token = get_token(data, request)
            ingestion_context, db_error, error_response = get_event_ingestion_context(request, data, request_token)
            return ingestion_context.team_id if ingestion_context else None
        except:
            return None
