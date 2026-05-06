from typing import Any, cast

from django.contrib.postgres.search import TrigramWordSimilarity
from django.db.models import F, Model, Prefetch, Q, QuerySet, Value
from django.db.models.functions import Coalesce
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
from social_django.admin import UserSocialAuth

from posthog.api.routing import TeamAndOrgViewSetMixin
from posthog.api.shared import UserBasicSerializer
from posthog.constants import INTERNAL_BOT_EMAIL_SUFFIX
from posthog.event_usage import groups
from posthog.helpers.trigram_search import MAX_SEARCH_LENGTH, MIN_NAME_TRIGRAM_SIMILARITY, normalize_search_term
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


class OrganizationMemberSerializer(serializers.ModelSerializer):
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


@extend_schema(tags=["core", "platform_features"])
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
                description="Fuzzy match against member `first_name`, `last_name`, and `email` using Postgres trigram word similarity. Supports typos and prefix-as-you-type. Capped at 200 characters.",
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
        OrganizationMembership.objects.exclude(user__email__endswith=INTERNAL_BOT_EMAIL_SUFFIX)
        .filter(
            user__is_active=True,
        )
        .select_related("user")
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
        search = normalize_search_term(search)
        span = trace.get_current_span()
        span.set_attribute("organization_member.search.length", len(search))
        if not search:
            return queryset

        zero = Value(0.0)
        first_name_score = Coalesce(TrigramWordSimilarity(search, "user__first_name"), zero)
        last_name_score = Coalesce(TrigramWordSimilarity(search, "user__last_name"), zero)
        email_score = Coalesce(TrigramWordSimilarity(search, "user__email"), zero)

        return (
            queryset.annotate(
                _first_name_score=first_name_score,
                _last_name_score=last_name_score,
                _email_score=email_score,
            )
            .filter(
                Q(_first_name_score__gt=MIN_NAME_TRIGRAM_SIMILARITY)
                | Q(_last_name_score__gt=MIN_NAME_TRIGRAM_SIMILARITY)
                | Q(_email_score__gt=MIN_NAME_TRIGRAM_SIMILARITY)
            )
            .annotate(_search_score=F("_first_name_score") + F("_last_name_score") + F("_email_score"))
            .order_by("-_search_score", "user__first_name")
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
