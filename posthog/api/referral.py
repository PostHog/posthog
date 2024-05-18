import structlog
from django.db.models import Count
from django.http import JsonResponse
from django_filters.rest_framework import DjangoFilterBackend
from rest_framework import exceptions, mixins, permissions, serializers, viewsets
from rest_framework.decorators import action
from rest_framework.request import Request
from rest_framework.response import Response

from posthog.api.forbid_destroy_model import ForbidDestroyModel
from posthog.api.routing import TeamAndOrgViewSetMixin
from posthog.api.shared import UserBasicSerializer
from posthog.models.referrals import ReferralProgram, ReferralProgramReferrer
from posthog.models.referrals.referral_program_redeemer import ReferralProgramRedeemer
from posthog.models.team.team import Team

logger = structlog.get_logger(__name__)


class ReferralProgramSerializer(serializers.ModelSerializer):
    created_by = UserBasicSerializer(read_only=True)

    redeemers_count = serializers.SerializerMethodField()
    referrers_count = serializers.SerializerMethodField()

    class Meta:
        model = ReferralProgram
        fields = [
            "short_id",
            "title",
            "description",
            "max_total_redemption_count",
            "max_redemption_count_per_referrer",
            "redeemers_count",
            "referrers_count",
            "created_at",
            "created_by",
        ]
        read_only_fields = ["short_id", "redeemers_count", "referrers_count", "created_at", "created_by"]

    def get_redeemers_count(self, obj: ReferralProgram) -> int:
        return obj.redeemers__count if hasattr(obj, "redeemers__count") else 0

    def get_referrers_count(self, obj: ReferralProgram) -> int:
        return obj.referrers__count if hasattr(obj, "referrers__count") else 0

    def create(self, validated_data: dict, *args, **kwargs) -> ReferralProgram:
        request = self.context["request"]
        validated_data["created_by"] = request.user
        validated_data["team_id"] = self.context["team_id"]

        return super().create(validated_data, *args, **kwargs)


class ReferralProgramRedeemerSerializer(serializers.ModelSerializer):
    class Meta:
        model = ReferralProgramRedeemer
        fields = ["user_id", "referrer", "points_awarded", "created_at", "email"]
        read_only_fields = [
            "user_id",
            "referrer",
            "points_awarded",
            "created_at",
        ]


class ReferralProgramReferrerSerializer(serializers.ModelSerializer):
    total_redemptions = serializers.SerializerMethodField()
    redeemers = ReferralProgramRedeemerSerializer(many=True, read_only=True, source="redeemer")

    class Meta:
        model = ReferralProgramReferrer
        fields = ["user_id", "code", "max_redemption_count", "total_redemptions", "created_at", "email", "redeemers"]
        read_only_fields = ["code", "max_redemption_count", "created_at", "total_redemptions"]

    def get_total_redemptions(self, obj: ReferralProgramReferrer) -> int:
        # TODO: This should be the plural but for some reason it isn't...
        return obj.redeemer.count()

    def create(self, validated_data: dict, *args, **kwargs) -> ReferralProgram:
        context = self.context

        rp = ReferralProgram.objects.get(short_id=context["referral_program_id"], team_id=context["team_id"])
        validated_data["referral_program_id"] = rp.id

        return super().create(validated_data, *args, **kwargs)


class ReferralProgramViewset(TeamAndOrgViewSetMixin, ForbidDestroyModel, viewsets.ModelViewSet):
    scope_object = "INTERNAL"
    queryset = (
        ReferralProgram.objects.annotate(Count("redeemers", distinct=True))
        .annotate(Count("referrers", distinct=True))
        .all()
    )
    filter_backends = [DjangoFilterBackend]
    filterset_fields = ["short_id"]
    lookup_field = "short_id"
    serializer_class = ReferralProgramSerializer


class ReferralProgramReferrerViewset(TeamAndOrgViewSetMixin, ForbidDestroyModel, viewsets.ModelViewSet):
    scope_object = "INTERNAL"
    queryset = ReferralProgramReferrer.objects.prefetch_related("redeemer").annotate(Count("redeemers")).all()
    filter_backends = [DjangoFilterBackend]
    filterset_fields = ["user_id", "code", "email"]
    lookup_field = "user_id"
    serializer_class = ReferralProgramReferrerSerializer
    filter_rewrite_rules = {"referral_program_id": "referral_program__short_id", "team_id": "referral_program__team_id"}


class ReferrerProgramRedeemerViewSet(
    TeamAndOrgViewSetMixin, ForbidDestroyModel, mixins.ListModelMixin, viewsets.GenericViewSet
):
    scope_object = "INTERNAL"
    queryset = ReferralProgramRedeemer.objects.all()
    filter_backends = [DjangoFilterBackend]
    filterset_fields = ["user_id", "referrer_id"]
    lookup_field = "user_id"
    serializer_class = ReferralProgramRedeemerSerializer
    filter_rewrite_rules = {"referral_program_id": "referral_program__short_id", "team_id": "referral_program__team_id"}


class PublicReferralsViewset(viewsets.GenericViewSet):
    permission_classes = (permissions.AllowAny,)

    def get_object(self):
        lookup_value = self.kwargs[self.lookup_field]

        token = self.request.query_params.get("token")
        team = Team.objects.get_team_from_cache_or_token(token=token)

        if not team:
            raise exceptions.ValidationError("token and id for the referral program are required")

        return ReferralProgram.objects.get(short_id=lookup_value, team=team)

    def list(self, request: Request):
        return JsonResponse({"scheme": "pyramid"}, status=200)

    def retrieve(self, request: Request, *args, **kwargs):
        program = self.get_object()

        # TODO: Swap to absolute minimal serializer
        data = ReferralProgramSerializer(program).data

        return Response(data)

    @action(methods=["get"], detail=True)
    def referrer(self, request: Request, *args, **kwargs):
        program = self.get_object()
        user_id = request.GET.get("user_id")
        user_email = request.GET.get("user_email")

        if not user_id:
            raise exceptions.ValidationError("Missing user_id")

        referrer, _ = ReferralProgramReferrer.objects.get_or_create(
            referral_program=program, user_id=user_id, defaults={"email": user_email}
        )
        data = ReferralProgramReferrerSerializer(referrer).data

        return Response(data)

    @action(methods=["get"], detail=True)
    def redeem(self, request: Request, *args, **kwargs):
        # NOTE: Should this be public???
        code = request.GET.get("code")
        user_id = request.GET.get("user_id")
        user_email = request.GET.get("user_email")
        if not code or not user_id:
            raise exceptions.ValidationError("Missing code")

        program = self.get_object()
        referrer = ReferralProgramReferrer.objects.get(referral_program=program, code=code)
        redeemer = ReferralProgramRedeemer.objects.create(
            referrer=referrer, referral_program=program, user_id=user_id, email=user_email
        )

        data = ReferralProgramRedeemerSerializer(redeemer).data

        # TODO: Track event including referrer and redeemer ids and emails

        return Response(data)
