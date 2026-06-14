from typing import Any, cast

from django.db.models import Count, Exists, OuterRef, Q, QuerySet

import structlog
import posthoganalytics
from drf_spectacular.utils import extend_schema
from rest_framework import mixins, status, viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import PermissionDenied
from rest_framework.permissions import BasePermission
from rest_framework.request import Request
from rest_framework.response import Response

from posthog.api.routing import TeamAndOrgViewSetMixin
from posthog.event_usage import report_user_action
from posthog.models import User
from posthog.permissions import get_organization_from_view
from posthog.rate_limit import PersonalApiKeyOrUserRateThrottle

from ..models.community_skills import CommunitySkill, CommunitySkillVote
from .community_skill_serializers import (
    ALLOWED_LIST_ORDERINGS,
    CommunitySkillInstallSerializer,
    CommunitySkillListQuerySerializer,
    CommunitySkillListSerializer,
    CommunitySkillSerializer,
    CommunitySkillVoteResponseSerializer,
)
from .community_skill_services import CommunitySkillNotFoundError, install_community_skill, toggle_community_skill_vote
from .skill_serializers import LLMSkillSerializer
from .skill_services import LLMSkillDuplicateNameConflictError, LLMSkillFileLimitError, LLMSkillFilePathConflictError

logger = structlog.get_logger(__name__)

COMMUNITY_SKILL_FEATURE_FLAG = "llm-analytics-community-skills"
# Installing copies into a regular LLMSkill, whose UI and APIs are gated by this base flag — so the
# marketplace also requires it, otherwise installed skills would be unreachable.
BASE_SKILL_FEATURE_FLAG = "llm-analytics-skills"


class CommunitySkillBurstThrottle(PersonalApiKeyOrUserRateThrottle):
    # Web-aware burst throttle: this endpoint is session-authenticated, so the default
    # PersonalApiKeyRateThrottle (personal-API-key only) would leave it unthrottled.
    scope = "burst"
    rate = "480/minute"


class CommunitySkillSustainedThrottle(PersonalApiKeyOrUserRateThrottle):
    scope = "sustained"
    rate = "4800/hour"


class CommunitySkillFeatureFlagPermission(BasePermission):
    def has_permission(self, request, view) -> bool:
        user = cast(User, request.user)
        organization = get_organization_from_view(view)
        org_id = str(organization.id)
        distinct_id = user.distinct_id or str(user.uuid)

        return all(
            bool(
                posthoganalytics.feature_enabled(
                    flag,
                    distinct_id,
                    groups={"organization": org_id},
                    group_properties={"organization": {"id": org_id}},
                    only_evaluate_locally=False,
                    send_feature_flag_events=False,
                )
            )
            for flag in (COMMUNITY_SKILL_FEATURE_FLAG, BASE_SKILL_FEATURE_FLAG)
        )


class CommunitySkillViewSet(
    TeamAndOrgViewSetMixin,
    mixins.ListModelMixin,
    mixins.RetrieveModelMixin,
    viewsets.GenericViewSet,
):
    # The community catalog is instance-global, so this endpoint is web-app only and not
    # exposed for personal-API-key scoping. Team context comes from the URL for install/vote.
    scope_object = "INTERNAL"
    serializer_class = CommunitySkillSerializer
    permission_classes = [CommunitySkillFeatureFlagPermission]
    lookup_field = "slug"

    def get_throttles(self):
        if self.action in ("install", "vote"):
            return [CommunitySkillBurstThrottle(), CommunitySkillSustainedThrottle()]
        return super().get_throttles()

    def dangerously_get_queryset(self) -> QuerySet[CommunitySkill]:
        # Deliberately bypasses team/parent filtering: CommunitySkill is a shared, instance-global
        # catalog with no team_id. Access is gated by the feature-flag permission above.
        user = cast(User, self.request.user)
        queryset = CommunitySkill.objects.filter(deleted=False).annotate(
            vote_count=Count("votes", distinct=True),
            has_voted=Exists(CommunitySkillVote.objects.filter(skill=OuterRef("pk"), user=user)),
        )
        # Only the detail serializer renders the files manifest — skip the extra query on list.
        if self.action != "list":
            queryset = queryset.prefetch_related("files")
        return queryset

    def get_serializer_class(self):
        if self.action == "list":
            return CommunitySkillListSerializer
        return super().get_serializer_class()

    @extend_schema(
        parameters=[CommunitySkillListQuerySerializer], responses={200: CommunitySkillListSerializer(many=True)}
    )
    def list(self, request: Request, *args, **kwargs) -> Response:
        params = CommunitySkillListQuerySerializer(data=request.query_params)
        params.is_valid(raise_exception=True)

        queryset = self.get_queryset()
        search = params.validated_data.get("search", "").strip()
        if search:
            # tags is a JSONField array — use `contains` for exact element membership, not a
            # substring match against the serialized JSON.
            queryset = queryset.filter(
                Q(name__icontains=search) | Q(description__icontains=search) | Q(tags__contains=[search])
            )
        tag = params.validated_data.get("tag", "").strip()
        if tag:
            queryset = queryset.filter(tags__contains=[tag])
        trust_tier = params.validated_data.get("trust_tier")
        if trust_tier:
            queryset = queryset.filter(trust_tier=trust_tier)

        order_by = params.validated_data.get("order_by", "-install_count")
        queryset = queryset.order_by(order_by if order_by in ALLOWED_LIST_ORDERINGS else "-install_count", "-id")

        page = self.paginate_queryset(queryset)
        if page is not None:
            serializer = self.get_serializer(page, many=True)
            return self.get_paginated_response(serializer.data)
        serializer = self.get_serializer(queryset, many=True)
        return Response({"count": len(serializer.data), "results": serializer.data})

    @extend_schema(request=CommunitySkillInstallSerializer, responses={201: LLMSkillSerializer})
    @action(methods=["POST"], detail=True)
    def install(self, request: Request, slug: str = "", **kwargs) -> Response:
        # Installing creates a durable LLMSkill in the team, so it must require the same write
        # access as LLMSkillViewSet's create (resource-level "editor" on llm_skill). The viewset
        # is scope_object="INTERNAL", so the shared AccessControlPermission only checks project
        # membership — enforce skill-write access imperatively here. Catalog reads (list/retrieve)
        # stay global and unaffected, and we avoid object-level AC checks against CommunitySkill
        # (which has no team and is not an LLMSkill).
        if not self.user_access_control.check_access_level_for_resource("llm_skill", "editor"):
            raise PermissionDenied("You do not have permission to install skills in this project.")

        payload = CommunitySkillInstallSerializer(data=request.data)
        payload.is_valid(raise_exception=True)

        try:
            installed = install_community_skill(
                team=self.team,
                user=cast(User, request.user),
                slug=slug,
                new_name=payload.validated_data.get("new_name"),
            )
        except CommunitySkillNotFoundError:
            return Response(
                {"detail": f"Community skill '{slug}' not found."},
                status=status.HTTP_404_NOT_FOUND,
            )
        except LLMSkillDuplicateNameConflictError:
            return Response(
                {"attr": "new_name", "detail": "A skill with this name already exists in your project."},
                status=status.HTTP_400_BAD_REQUEST,
            )
        except (LLMSkillFileLimitError, LLMSkillFilePathConflictError):
            # The synced community payload violates the skill limits (too many files / bad paths).
            return Response(
                {"detail": "This community skill can't be installed because its bundled files are invalid."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        report_user_action(
            cast(User, request.user),
            "community skill installed",
            {
                "community_skill_slug": slug,
                "installed_skill_name": installed.name,
            },
            team=self.team,
            request=request,
        )
        return Response(
            cast(dict[str, Any], LLMSkillSerializer(installed, context=self.get_serializer_context()).data),
            status=status.HTTP_201_CREATED,
        )

    @extend_schema(request=None, responses={200: CommunitySkillVoteResponseSerializer})
    @action(methods=["POST"], detail=True)
    def vote(self, request: Request, slug: str = "", **kwargs) -> Response:
        try:
            vote_count, has_voted = toggle_community_skill_vote(slug=slug, user=cast(User, request.user))
        except CommunitySkillNotFoundError:
            return Response(
                {"detail": f"Community skill '{slug}' not found."},
                status=status.HTTP_404_NOT_FOUND,
            )
        return Response({"vote_count": vote_count, "has_voted": has_voted})
