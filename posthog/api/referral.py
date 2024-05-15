from rest_framework.response import Response
import structlog
from django_filters.rest_framework import DjangoFilterBackend
from rest_framework import serializers, viewsets, mixins
from django.db.models import Count
from posthog.api.forbid_destroy_model import ForbidDestroyModel
from posthog.api.routing import TeamAndOrgViewSetMixin
from posthog.api.shared import UserBasicSerializer
from posthog.models.referrals import ReferralProgram, ReferralProgramReferrer
from posthog.models.referrals.referral_program_redeemer import ReferralProgramRedeemer

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


class ReferralProgramReferrerSerializer(serializers.ModelSerializer):
    class Meta:
        model = ReferralProgramReferrer
        fields = [
            "user_id",
            "code",
            "max_redemption_count",
            "created_at",
        ]
        read_only_fields = ["code", "max_redemption_count", "created_at"]

    def create(self, validated_data: dict, *args, **kwargs) -> ReferralProgram:
        context = self.context

        rp = ReferralProgram.objects.get(short_id=context["referral_program_id"], team_id=context["team_id"])
        validated_data["referral_program_id"] = rp.id

        return super().create(validated_data, *args, **kwargs)


class ReferralProgramRedeemerSerializer(serializers.ModelSerializer):
    referrer = ReferralProgramReferrerSerializer(read_only=True)

    class Meta:
        model = ReferralProgramRedeemer
        fields = [
            "user_id",
            "referrer",
            "points_awarded",
            "created_at",
        ]
        read_only_fields = [
            "user_id",
            "referrer",
            "points_awarded",
            "created_at",
        ]


class ReferralProgramViewset(TeamAndOrgViewSetMixin, ForbidDestroyModel, viewsets.ModelViewSet):
    scope_object = "INTERNAL"
    queryset = ReferralProgram.objects.annotate(Count("redeemers")).annotate(Count("referrers")).all()
    filter_backends = [DjangoFilterBackend]
    filterset_fields = ["short_id"]
    lookup_field = "short_id"
    serializer_class = ReferralProgramSerializer


class ReferralProgramReferrerViewset(TeamAndOrgViewSetMixin, ForbidDestroyModel, viewsets.ModelViewSet):
    scope_object = "INTERNAL"
    queryset = ReferralProgramReferrer.objects.all()
    filter_backends = [DjangoFilterBackend]
    filterset_fields = ["user_id", "code"]
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
