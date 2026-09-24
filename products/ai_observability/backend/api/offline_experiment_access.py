from typing import TYPE_CHECKING

from posthog.auth import PersonalAPIKeyAuthentication, ProjectSecretAPIKeyAuthentication
from posthog.rate_limit import PersonalApiKeyOrUserRateThrottle, PersonalOrProjectSecretApiKeyRateThrottle

if TYPE_CHECKING:
    from rest_framework.request import Request
    from rest_framework.views import APIView


class _OfflineEvaluationCallerThrottle(PersonalOrProjectSecretApiKeyRateThrottle):
    def allow_request(self, request: "Request", view: "APIView") -> bool:
        return self._allow_request_internal(request, view, personal_api_key_only=False)

    def get_cache_key(self, request: "Request", view: "APIView") -> str:
        if isinstance(
            request.successful_authenticator, (PersonalAPIKeyAuthentication, ProjectSecretAPIKeyAuthentication)
        ):
            return super().get_cache_key(request, view)
        ident = f"user:{request.user.pk}" if request.user.is_authenticated else self.get_ident(request)
        return self.cache_format % {"scope": self.scope, "ident": ident}


class OfflineEvaluationIngestionBurstThrottle(_OfflineEvaluationCallerThrottle):
    scope = "offline_evaluation_ingestion_burst"
    rate = "60/minute"


class OfflineEvaluationIngestionSustainedThrottle(_OfflineEvaluationCallerThrottle):
    scope = "offline_evaluation_ingestion_sustained"
    rate = "1000/hour"


class OfflineEvaluationIngestionTeamBurstThrottle(PersonalApiKeyOrUserRateThrottle):
    scope = "offline_evaluation_ingestion_team_burst"
    rate = "60/minute"

    def get_cache_key(self, request: "Request", view: "APIView") -> str:
        team_id = self.safely_get_team_id_from_view(view)
        return self.cache_format % {"scope": self.scope, "ident": f"team:{team_id}"}


class OfflineEvaluationIngestionTeamSustainedThrottle(OfflineEvaluationIngestionTeamBurstThrottle):
    scope = "offline_evaluation_ingestion_team_sustained"
    rate = "1000/hour"
