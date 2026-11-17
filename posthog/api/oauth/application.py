from drf_spectacular.utils import extend_schema, extend_schema_field
from rest_framework import mixins, serializers, viewsets

from posthog.api.oauth.provisioning_review import partner_provisioning_status
from posthog.api.routing import TeamAndOrgViewSetMixin
from posthog.models.oauth import OAuthApplication
from posthog.models.oauth_provisioning_review import (
    CIMDProvisioningReview,
    PartnerProvisioningStatus,
    ProvisioningReviewStatus,
)
from posthog.models.utils import strict_fetch
from posthog.permissions import OrganizationAdminReadPermissions


class PartnerReviewSerializer(serializers.ModelSerializer):
    """The review an app went through to become a provisioning partner, as its owners see it.

    The verdict's internal reason and the evidence stay with PostHog staff: they describe what the
    review checks, which would teach an abusive app what to fake.
    """

    status = serializers.ChoiceField(
        choices=ProvisioningReviewStatus.choices,
        read_only=True,
        help_text=(
            "pending: the automated review is running. needs_human: PostHog staff decide next. "
            "accepted: the app may provision. rejected: provisioning is blocked."
        ),
    )
    opened_at = serializers.DateTimeField(
        source="created_at", read_only=True, help_text="When the app registered for provisioning."
    )
    decided_at = serializers.DateTimeField(
        read_only=True, allow_null=True, help_text="When the current decision was made. Null while pending."
    )
    partner_message = serializers.CharField(
        read_only=True,
        help_text="What PostHog staff wrote to the app's owners about the decision. Empty when they wrote nothing.",
    )

    class Meta:
        model = CIMDProvisioningReview
        fields = ["status", "opened_at", "decided_at", "partner_message"]


class OrganizationOAuthApplicationSerializer(serializers.ModelSerializer):
    """Serializer for organization-scoped OAuth applications (read-only)."""

    redirect_uris_list = serializers.SerializerMethodField()
    is_cimd_client = serializers.BooleanField(
        read_only=True,
        help_text="True when the app registered itself from a client ID metadata document (CIMD).",
    )
    provisioning_status = serializers.SerializerMethodField()
    provisioning_review = serializers.SerializerMethodField()

    class Meta:
        model = OAuthApplication
        fields = [
            "id",
            "name",
            "client_id",
            "redirect_uris_list",
            "is_verified",
            "is_cimd_client",
            "provisioning_status",
            "provisioning_review",
            "created",
            "updated",
        ]

    @extend_schema_field(serializers.ListField(child=serializers.CharField()))
    def get_redirect_uris_list(self, instance: OAuthApplication) -> list[str]:
        return instance.redirect_uris.split() if instance.redirect_uris else []

    @extend_schema_field(
        serializers.ChoiceField(
            choices=PartnerProvisioningStatus.choices,
            help_text=(
                "Whether the app can create accounts and provision resources through the agentic provisioning API. "
                "in_review and waiting_for_staff mean its review has not finished."
            ),
        )
    )
    def get_provisioning_status(self, instance: OAuthApplication) -> str:
        return partner_provisioning_status(instance, _review(instance))

    @extend_schema_field(PartnerReviewSerializer(allow_null=True))
    def get_provisioning_review(self, instance: OAuthApplication) -> dict | None:
        review = _review(instance)
        return PartnerReviewSerializer(review).data if review is not None else None


def _review(app: OAuthApplication) -> CIMDProvisioningReview | None:
    return getattr(app, "provisioning_review", None)


@extend_schema(extensions={"x-product": "core"})
class OrganizationOAuthApplicationViewSet(
    TeamAndOrgViewSetMixin,
    mixins.ListModelMixin,
    mixins.RetrieveModelMixin,
    viewsets.GenericViewSet,
):
    """
    OAuth applications linked to the organization, with each app's provisioning partner status and
    review. Read-only, and only for organization admins, who are the people who run the apps.
    """

    scope_object = "organization"
    permission_classes = [OrganizationAdminReadPermissions]
    queryset = (
        OAuthApplication.objects.select_related("provisioning_review")
        # Partners see the verdict, not the research behind it, and these fields can be large.
        .defer(
            "provisioning_review__metadata_document",
            "provisioning_review__research_evidence",
            "provisioning_review__research_judgment",
            "provisioning_review__run_log",
        )
        .order_by("-created")
    )
    serializer_class = OrganizationOAuthApplicationSerializer

    def safely_get_queryset(self, queryset):
        queryset = queryset.filter(organization=self.organization)
        return strict_fetch(queryset) if self.action == "list" else queryset
