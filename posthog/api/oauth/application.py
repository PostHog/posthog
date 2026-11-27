from typing import cast

from drf_spectacular.types import OpenApiTypes
from drf_spectacular.utils import OpenApiResponse, extend_schema, extend_schema_field
from rest_framework import exceptions, mixins, serializers, viewsets
from rest_framework.decorators import action
from rest_framework.response import Response

from posthog.api.mixins import ValidatedRequest, validated_request
from posthog.api.oauth.provisioning_review import (
    PARTNER_NOTE_MAX_LENGTH,
    PartnerNoteRefused,
    partner_message_for_current_organization,
    partner_provisioning_status,
    partner_timeline,
    registered_partner_details,
    send_partner_note,
)
from posthog.api.routing import TeamAndOrgViewSetMixin
from posthog.models.oauth import OAuthApplication
from posthog.models.oauth_provisioning_review import (
    CIMDProvisioningReview,
    OrganizationLinkState,
    PartnerAuthentication,
    PartnerProvisioningStatus,
    PartnerReviewEventKind,
    ProvisioningReviewStatus,
)
from posthog.models.user import User
from posthog.models.utils import strict_fetch
from posthog.permissions import OrganizationAdminReadPermissions


class PartnerReviewEventSerializer(serializers.Serializer):
    at = serializers.DateTimeField(read_only=True, help_text="When it happened.")
    kind = serializers.ChoiceField(
        choices=PartnerReviewEventKind.choices,
        read_only=True,
        help_text=(
            "registered: the app registered for provisioning. automated_review: the automated review decided. "
            "staff_decision: PostHog staff decided. staff_message: PostHog staff changed their message. "
            "partner_note: an admin of the app's organization sent a note."
        ),
    )
    status = serializers.ChoiceField(
        choices=ProvisioningReviewStatus.choices,
        read_only=True,
        allow_null=True,
        help_text="The review status the event left. Null for registrations and notes.",
    )
    message = serializers.CharField(
        read_only=True,
        help_text="What PostHog staff wrote to the app's owners, or the text of the note. Empty when there is none.",
    )
    author = serializers.CharField(
        read_only=True, help_text="The email of the admin who sent a note. Empty for every other event."
    )


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
            "accepted: the app may provision. changes_requested: PostHog staff asked for changes or more "
            "information, so send a review note. declined: not approved, and a review note asks for another review. "
            "rejected: provisioning is blocked, and only PostHog staff can lift it."
        ),
    )
    opened_at = serializers.DateTimeField(
        source="created_at", read_only=True, help_text="When the app registered for provisioning."
    )
    decided_at = serializers.DateTimeField(
        read_only=True, allow_null=True, help_text="When the current decision was made. Null while pending."
    )
    partner_message = serializers.SerializerMethodField(
        help_text="What PostHog staff wrote to the app's owners about the decision. Empty when they wrote nothing, or wrote it while the app was linked to another organization.",
    )
    timeline = serializers.SerializerMethodField(
        help_text="What happened on the review, oldest first: decisions, messages from PostHog staff, and notes."
    )

    class Meta:
        model = CIMDProvisioningReview
        fields = ["status", "opened_at", "decided_at", "partner_message", "timeline"]

    @extend_schema_field(OpenApiTypes.STR)
    def get_partner_message(self, instance: CIMDProvisioningReview) -> str:
        return partner_message_for_current_organization(instance)

    @extend_schema_field(PartnerReviewEventSerializer(many=True))
    def get_timeline(self, instance: CIMDProvisioningReview) -> list[dict]:
        return list(PartnerReviewEventSerializer(partner_timeline(instance), many=True).data)


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


class PartnerReviewNoteSerializer(serializers.Serializer):
    note = serializers.CharField(
        max_length=PARTNER_NOTE_MAX_LENGTH,
        help_text=(
            "What PostHog staff should know about the application: what it does, why it provisions, and what changed "
            "since the last decision. Sending a note on a declined review, or one that asked for changes, asks for "
            "another review."
        ),
    )


class RegisteredPartnerDetailsSerializer(serializers.Serializer):
    client_name = serializers.CharField(read_only=True, help_text="The app's name, as of its last metadata refresh.")
    client_uri = serializers.CharField(
        read_only=True, help_text="The homepage in the document saved when the review opened. Empty when it had none."
    )
    logo_uri = serializers.CharField(read_only=True, help_text="The app's logo, as of its last metadata refresh.")
    tos_uri = serializers.CharField(
        read_only=True,
        help_text="The terms of service in the document saved when the review opened. Empty when it had none.",
    )
    policy_uri = serializers.CharField(
        read_only=True,
        help_text="The privacy policy in the document saved when the review opened. Empty when it had none.",
    )
    contacts = serializers.ListField(
        child=serializers.CharField(),
        read_only=True,
        help_text="Contact emails in the document saved when the review opened.",
    )
    redirect_uris = serializers.ListField(
        child=serializers.CharField(),
        read_only=True,
        help_text="Where PostHog sends people after they sign in, as of the last metadata refresh.",
    )
    jwks_uri = serializers.CharField(
        read_only=True, help_text="Where the app publishes the public keys it signs with. Empty for a public client."
    )
    authentication = serializers.ChoiceField(
        choices=PartnerAuthentication.choices,
        read_only=True,
        help_text="How the app authenticates: none (public client), client_secret_post, or private_key_jwt.",
    )
    scopes = serializers.ListField(
        child=serializers.CharField(), read_only=True, help_text="Every scope the app can ask people to grant."
    )
    uses_default_scopes = serializers.BooleanField(
        read_only=True,
        help_text="Whether the scopes are PostHog's default set, because the app names no scopes or asks for @default.",
    )
    needs_signing_key = serializers.BooleanField(
        read_only=True,
        help_text="Whether PostHog refuses the app's provisioning requests because it has no private key to sign them with.",
    )
    can_create_accounts = serializers.BooleanField(
        read_only=True, help_text="Whether the app can create PostHog accounts once provisioning is on."
    )
    can_provision_resources = serializers.BooleanField(
        read_only=True, help_text="Whether the app can create projects and resources once provisioning is on."
    )
    organization_link = serializers.ChoiceField(
        choices=OrganizationLinkState.choices,
        read_only=True,
        help_text="Whether a verification token links the app to this organization, to one in another region, or to none.",
    )
    metadata_document = serializers.CharField(
        read_only=True,
        help_text="The metadata document saved when the review opened, as formatted JSON. Empty when PostHog kept none.",
    )


class OrganizationOAuthApplicationDetailSerializer(OrganizationOAuthApplicationSerializer):
    """One application, with what PostHog read from its metadata document."""

    registration = serializers.SerializerMethodField()

    class Meta(OrganizationOAuthApplicationSerializer.Meta):
        fields = [*OrganizationOAuthApplicationSerializer.Meta.fields, "registration"]

    @extend_schema_field(RegisteredPartnerDetailsSerializer)
    def get_registration(self, instance: OAuthApplication) -> dict:
        return RegisteredPartnerDetailsSerializer(registered_partner_details(instance, _review(instance))).data


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
        # Partners see the verdict and the timeline built from the run log, not the research behind it, and these
        # fields can be large.
        .defer(
            "provisioning_review__metadata_document",
            "provisioning_review__research_evidence",
            "provisioning_review__research_judgment",
        )
        .order_by("-created")
    )
    serializer_class = OrganizationOAuthApplicationSerializer

    @validated_request(
        request_serializer=PartnerReviewNoteSerializer,
        responses={
            200: OpenApiResponse(
                response=OrganizationOAuthApplicationDetailSerializer,
                description="The application with its review, which is back with PostHog staff.",
            ),
        },
        summary="Send a note on the app's provisioning review",
        description=(
            "Tell PostHog staff about the application. On a declined review, or one where staff asked for changes, "
            "the note asks for another review. A blocked application cannot send one."
        ),
    )
    @action(detail=True, methods=["post"], url_path="review_note", required_scopes=["organization:write"])
    def review_note(self, request: ValidatedRequest, *args, **kwargs) -> Response:
        app = self.get_object()
        try:
            send_partner_note(app, user=cast(User, request.user), note=request.validated_data["note"])
        except PartnerNoteRefused as refused:
            raise exceptions.ValidationError({"note": str(refused)})
        app = self.get_queryset().get(pk=app.pk)
        return Response(self.get_serializer(app).data)

    def get_serializer_class(self):
        if self.action == "list":
            return OrganizationOAuthApplicationSerializer
        return OrganizationOAuthApplicationDetailSerializer

    def safely_get_queryset(self, queryset):
        queryset = queryset.filter(organization=self.organization)
        return strict_fetch(queryset) if self.action == "list" else queryset
