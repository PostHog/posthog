from typing import Any, cast

from django.db.models import F, Model, Prefetch, QuerySet
from django.shortcuts import get_object_or_404

from django_otp.plugins.otp_totp.models import TOTPDevice
from drf_spectacular.types import OpenApiTypes
from drf_spectacular.utils import OpenApiParameter, extend_schema, extend_schema_view
from opentelemetry import trace
from rest_framework import exceptions, mixins, serializers, viewsets
from rest_framework.decorators import action
from rest_framework.permissions import SAFE_METHODS, BasePermission
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.serializers import raise_errors_on_nested_writes

# Import from `.models`, not `.admin`. `social_django.admin` re-exports
# `UserSocialAuth` for convenience, but importing that module triggers
# `@admin.register(UserSocialAuth)` as a setup-time side effect — and
# `PostHogConfig.ready()` later wraps `admin.site._registry` with
# `LazyAdminRegistry`, throwing the registration away. `.models` is the
# semantically-correct source for the model class and keeps the setup-time
# admin-import surface as small as possible.
from social_django.models import UserSocialAuth

from posthog.api.routing import TeamAndOrgViewSetMixin
from posthog.api.shared import SearchMatchTypeSerializerMixin, UserBasicSerializer
from posthog.constants import INTERNAL_BOT_EMAIL_SUFFIX
from posthog.event_usage import groups
from posthog.helpers.trigram_search import (
    MAX_SEARCH_LENGTH,
    TrigramSearchField,
    apply_trigram_search,
    normalize_search_term,
)
from posthog.models import OrganizationMembership
from posthog.models.user import User
from posthog.models.webauthn_credential import WebauthnCredential
from posthog.permissions import TimeSensitiveActionPermission, extract_organization
from posthog.utils import posthoganalytics

tracer = trace.get_tracer(__name__)

# Only index-backed orderings are allowed. `-joined_at` is served by the
# `(organization, -joined_at)` composite index; other fields would force a
# full scan + sort and can time out for large organizations.
ALLOWED_ORDERINGS = frozenset({"joined_at", "-joined_at"})
DEFAULT_ORDERING = "-joined_at"


def organization_members_base_queryset() -> QuerySet:
    """Active, non-bot organization memberships with their user prefetched.

    Shared base for organization-member listings (core admin view and the
    customer-analytics account view) so the exclusion and active-user filter
    stay in one place.
    """
    return (
        OrganizationMembership.objects.exclude(user__email__endswith=INTERNAL_BOT_EMAIL_SUFFIX)
        .filter(user__is_active=True)
        .select_related("user")
    )


class OrganizationMemberObjectPermissions(BasePermission):
    """Require organization admin level to change object, allowing everyone read AND delete."""

    message = "Your cannot edit other organization members."

    def has_object_permission(self, request: Request, view, membership: OrganizationMembership) -> bool:
        if request.method in SAFE_METHODS:
            return True
        organization = extract_organization(membership, view)
        requesting_membership: OrganizationMembership = OrganizationMembership.objects.get(
            user_id=cast(User, request.user).id,
            organization=organization,
        )
        try:
            requesting_membership.validate_update(membership)
        except exceptions.ValidationError:
            return False
        return True


class OrganizationMemberSerializer(SearchMatchTypeSerializerMixin, serializers.ModelSerializer):
    user = UserBasicSerializer(read_only=True)
    is_2fa_enabled = serializers.SerializerMethodField()
    has_social_auth = serializers.SerializerMethodField()
    last_login = serializers.DateTimeField(read_only=True)

    class Meta:
        model = OrganizationMembership
        fields = [
            "id",
            "user",
            "level",
            "joined_at",
            "updated_at",
            "is_2fa_enabled",
            "has_social_auth",
            "last_login",
            "search_match_type",
        ]
        read_only_fields = ["id", "joined_at", "updated_at"]

    def get_is_2fa_enabled(self, instance: OrganizationMembership) -> bool:
        # Uses prefetched relations to avoid N+1 queries
        user = instance.user
        has_totp = len(user.totpdevice_set.all()) > 0  # type: ignore[attr-defined]
        has_passkeys_for_2fa = bool(user.passkeys_enabled_for_2fa) and len(user.webauthn_credentials.all()) > 0
        return has_totp or has_passkeys_for_2fa

    def get_has_social_auth(self, instance: OrganizationMembership) -> bool:
        return len(instance.user.social_auth.all()) > 0

    def update(self, instance: OrganizationMembership, validated_data: dict[str, object]) -> OrganizationMembership:
        updated_membership = instance
        raise_errors_on_nested_writes("update", self, validated_data)
        requesting_membership: OrganizationMembership = OrganizationMembership.objects.get(
            organization=updated_membership.organization,
            user=self.context["request"].user,
        )
        for attr, value in validated_data.items():
            if attr == "level":
                requesting_membership.validate_update(
                    updated_membership, cast(OrganizationMembership.Level | None, value)
                )
            setattr(updated_membership, attr, value)
        updated_membership.save()
        return updated_membership


class OrganizationMemberGithubLoginSerializer(serializers.Serializer):
    github_login = serializers.CharField(
        allow_null=True,
        help_text=(
            "The member's GitHub username (login), resolved from their linked GitHub integration or OAuth "
            "identity. Null when the member has no GitHub identity linked."
        ),
    )


@extend_schema(extensions={"x-product": "platform_features"})
@extend_schema_view(
    list=extend_schema(
        parameters=[
            OpenApiParameter(
                name="order",
                type=OpenApiTypes.STR,
                location=OpenApiParameter.QUERY,
                required=False,
                enum=sorted(ALLOWED_ORDERINGS),
                description=f"Sort order. Defaults to `{DEFAULT_ORDERING}`.",
            ),
            OpenApiParameter(
                name="search",
                type=OpenApiTypes.STR,
                description="Match against member `first_name`, `last_name`, and `email`. Returns case-insensitive substring matches and fuzzy trigram matches (typos, prefix-as-you-type) together, ordered exact-first; each result's `search_match_type` is `exact` or `similar`. Capped at 200 characters.",
            ),
        ],
    ),
)
class OrganizationMemberViewSet(
    TeamAndOrgViewSetMixin,
    mixins.DestroyModelMixin,
    mixins.UpdateModelMixin,
    mixins.ListModelMixin,
    viewsets.GenericViewSet,
):
    scope_object = "organization_member"
    serializer_class = OrganizationMemberSerializer
    permission_classes = [OrganizationMemberObjectPermissions, TimeSensitiveActionPermission]
    queryset = (
        organization_members_base_queryset()
        .prefetch_related(
            Prefetch(
                "user__totpdevice_set",
                queryset=TOTPDevice.objects.filter(confirmed=True),
            ),
            Prefetch("user__social_auth", queryset=UserSocialAuth.objects.all()),
            Prefetch(
                "user__webauthn_credentials",
                queryset=WebauthnCredential.objects.filter(verified=True),
            ),
        )
        .annotate(last_login=F("user__last_login"))
    )
    lookup_field = "user__uuid"

    def safely_get_object(self, queryset):
        lookup_value = self.kwargs[self.lookup_field]
        if lookup_value == "@me":
            return queryset.get(user=self.request.user)
        filter_kwargs = {self.lookup_field: lookup_value}
        return get_object_or_404(queryset, **filter_kwargs)

    @tracer.start_as_current_span("OrganizationMemberViewSet.list")
    def list(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        response = super().list(request, *args, **kwargs)
        if request.query_params.get("search"):
            data = response.data if isinstance(response.data, dict) else {}
            results_len = data.get("count", len(data.get("results", [])))
            span = trace.get_current_span()
            span.set_attribute("organization_member.search.result_count", results_len)
            span.set_attribute("organization_member.search.empty", results_len == 0)
        return response

    @staticmethod
    @tracer.start_as_current_span("OrganizationMemberViewSet._apply_search")
    def _apply_search(queryset: QuerySet, search: str) -> QuerySet:
        return apply_trigram_search(
            queryset,
            search,
            span_prefix="organization_member.search",
            fields=(
                TrigramSearchField("user__first_name"),
                TrigramSearchField("user__last_name"),
                TrigramSearchField("user__email"),
            ),
            tiebreakers=("user__first_name",),
        )

    def safely_get_queryset(self, queryset) -> QuerySet:
        if self.action == "list":
            params = self.request.GET.dict()

            if "email" in params:
                queryset = queryset.filter(user__email=params["email"])

            if "updated_after" in params:
                queryset = queryset.filter(updated_at__gt=params["updated_after"])

            search = self.request.GET.get("search", "")
            if len(search) > MAX_SEARCH_LENGTH:
                raise serializers.ValidationError(
                    {"search": f"Search query must be {MAX_SEARCH_LENGTH} characters or fewer."}
                )
            # Normalize before deciding so whitespace-only queries fall through to default
            # ordering rather than reaching `_apply_search` and returning the queryset
            # without any order applied.
            if normalize_search_term(search):
                queryset = self._apply_search(queryset, search)
            else:
                order = self.request.GET.get("order")
                if order in ALLOWED_ORDERINGS:
                    queryset = queryset.order_by(order)
                else:
                    queryset = queryset.order_by(DEFAULT_ORDERING)

        return queryset

    def perform_destroy(self, instance: Model):
        instance = cast(OrganizationMembership, instance)
        requesting_user = cast(User, self.request.user)
        removed_user = cast(User, instance.user)

        is_self_removal = requesting_user.id == removed_user.id

        posthoganalytics.capture(
            distinct_id=str(requesting_user.distinct_id),
            event="organization member removed",
            properties={
                "removed_member_id": removed_user.distinct_id,
                "removed_by_id": requesting_user.distinct_id,
                "organization_id": instance.organization_id,
                "organization_name": instance.organization.name,
                "removal_type": "self_removal" if is_self_removal else "removed_by_other",
                "removed_email": removed_user.email,
                "removed_user_id": removed_user.id,
            },
            groups=groups(instance.organization),
        )

        instance.user.leave(organization=instance.organization)

    @extend_schema(responses=OrganizationMemberGithubLoginSerializer)
    @action(detail=True, methods=["get"], url_path="github_login", required_scopes=["organization_member:read"])
    def github_login(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        instance = cast(OrganizationMembership, self.get_object())
        return Response({"github_login": instance.user.get_github_login()})

    @action(detail=True, methods=["get"])
    def scoped_api_keys(self, request, *args, **kwargs):
        instance = self.get_object()
        api_keys_data = instance.get_scoped_api_keys()

        return Response(
            {
                "has_keys": api_keys_data["has_keys"],
                "has_keys_active_last_week": api_keys_data["has_keys_active_last_week"],
                "keys": api_keys_data["keys"],
            }
        )
