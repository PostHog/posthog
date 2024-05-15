import structlog
from django_filters.rest_framework import DjangoFilterBackend
from rest_framework import serializers, viewsets

from posthog.api.forbid_destroy_model import ForbidDestroyModel
from posthog.api.routing import TeamAndOrgViewSetMixin
from posthog.api.shared import UserBasicSerializer
from posthog.models.referrals import ReferralProgram, ReferralProgramReferrer

logger = structlog.get_logger(__name__)


class ReferralProgramSerializer(serializers.ModelSerializer):
    created_by = UserBasicSerializer(read_only=True)

    class Meta:
        model = ReferralProgram
        fields = [
            "short_id",
            "title",
            "description",
            "max_total_redemption_count",
            "max_redemption_count_per_referrer",
            "created_at",
            "created_by",
        ]
        read_only_fields = ["short_id", "created_at", "created_by"]

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
        return super().create(validated_data, *args, **kwargs)


class ReferralProgramViewset(TeamAndOrgViewSetMixin, ForbidDestroyModel, viewsets.ModelViewSet):
    scope_object = "INTERNAL"
    queryset = ReferralProgram.objects.all()
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
