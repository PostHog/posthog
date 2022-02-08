import typing
from typing import Optional

import reversion
import structlog
from django.http.request import HttpRequest
from reversion.revisions import create_revision
from reversion.views import get_user, set_user

from posthog.models.revision_team_metadata import RevisionTeamMetadata

VERSIONING_EXCLUSIONS = ["/e/", "/s/", "/decide/"]


class TeamAwareVersioning:
    """
    Based on `from reversion.middleware import RevisionMiddleware`
    But different enough to not beed to inherit from it
    """

    def __init__(self, get_response):
        self.get_response = get_response
        self.logger = structlog.get_logger(__name__)

    def request_creates_revision(self, request: HttpRequest) -> typing.Tuple[bool, Optional[int]]:
        """
        Reversion tries to create a revision for any request that isn't OPTION, GET or HEAD

        There are some URLs that can be on a deny-list since we know they are called frequently
        but never generate a version

        Returns whether this request might create a revision, and the detected team id

        Must be able to detect a team id to create a revision
        """
        reversion_would_by_default_create_a_revision = request.method not in ("OPTIONS", "GET", "HEAD")

        if request.path in VERSIONING_EXCLUSIONS:
            return False, None

        if reversion_would_by_default_create_a_revision:
            team_id = self._get_team_id_from_request(request)
            return reversion_would_by_default_create_a_revision and team_id, team_id
        else:
            return False, None

    def __call__(self, request, *args, **kwargs):
        request_creates_revision, team_id = self.request_creates_revision(request)
        if request_creates_revision:
            with create_revision(manage_manually=False, using=None, atomic=True):
                reversion.add_meta(RevisionTeamMetadata, team_id=team_id)
                self.logger.info(
                    f"[VERSIONING] creating revision", team_id=team_id, url=request.get_raw_uri(),
                )
                response = self.get_response(request, *args, **kwargs)
                if getattr(request, "user", None) and request.user.is_authenticated and get_user() is None:
                    set_user(request.user)

                return response

        return self.get_response(request, *args, **kwargs)

    def _get_team_id_from_request(self, request) -> Optional[int]:
        try:
            return request.user.current_team_id
        except:
            self.logger.info(
                "Error getting team_id from user", request_path=request.path, url=request.get_raw_uri(),
            )
            return None
