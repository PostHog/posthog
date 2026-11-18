from typing import Any, cast

from drf_spectacular.utils import OpenApiResponse
from rest_framework import serializers, viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import PermissionDenied
from rest_framework.request import Request
from rest_framework.response import Response

from posthog.api.mixins import validated_request
from posthog.api.routing import TeamAndOrgViewSetMixin
from posthog.auth import SessionAuthentication
from posthog.decorators import disallow_if_impersonated
from posthog.event_usage import report_user_action
from posthog.models.user import User

from products.cohorts.backend.facade.realtime_join import RealtimeCohortsJoinState, join_state, request_join


class RealtimeCohortsJoinStateSerializer(serializers.Serializer):
    state = serializers.ChoiceField(
        choices=RealtimeCohortsJoinState.choices,
        help_text="Where this project stands in joining the realtime cohorts beta. `serving`: the project has "
        "realtime cohorts. `setting_up`: a join is in progress. `available`: a POST to `join` starts one. "
        "`not_open`: this region takes no new projects. `refused`: the project cannot join by itself, and support "
        "can turn realtime cohorts on for it. `failed`: the last join did not finish, and a join an hour later "
        "tries again.",
    )


class RealtimeCohortsViewSet(TeamAndOrgViewSetMixin, viewsets.GenericViewSet):
    scope_object = "cohort"
    # A join acts on the whole project, so access to a single cohort is not enough.
    requires_resource_level_access = True

    # DRF gives the mapped POST these scopes too. View access is enough to join from the app, because a join turns
    # realtime on for no cohort, and a member who cannot edit cohorts cannot turn it on for one.
    @validated_request(
        responses={200: OpenApiResponse(response=RealtimeCohortsJoinStateSerializer)},
        description="Where this project stands in joining the realtime cohorts beta.",
    )
    @action(methods=["GET"], detail=False, required_scopes=["cohort:read"])
    def join(self, request: Request, **kwargs: Any) -> Response:
        return self._join_state_response()

    @validated_request(
        responses={200: OpenApiResponse(response=RealtimeCohortsJoinStateSerializer)},
        description="Join the realtime cohorts beta for this project when it can join by itself, and return where "
        "it stands. A repeated call starts nothing more.",
    )
    @join.mapping.post
    @disallow_if_impersonated(message="Impersonated sessions cannot join the realtime cohorts beta.")
    def start_join(self, request: Request, **kwargs: Any) -> Response:
        # The read scope also admits tokens, and a read-only token must not start the work of `enable`, which resaves
        # the project's cohorts.
        if not isinstance(request.successful_authenticator, SessionAuthentication):
            raise PermissionDenied(
                "API keys and tokens cannot join the realtime cohorts beta. Join from the PostHog app."
            )
        user = cast(User, request.user)
        if request_join(self._root_team_id, requested_by_id=user.id):
            # The root project, because the task reports the join's outcome against it.
            root_team = self.team.parent_team or self.team
            report_user_action(user, "realtime cohorts join requested", team=root_team, request=request)
        return self._join_state_response()

    @property
    def _root_team_id(self) -> int:
        # Cohorts and access rows live on the root team, so a child environment joins through it.
        return self.team.parent_team_id or self.team.id

    def _join_state_response(self) -> Response:
        return Response(RealtimeCohortsJoinStateSerializer({"state": join_state(self._root_team_id)}).data)
