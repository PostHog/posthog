from uuid import UUID

from django.db.models import F, Q, QuerySet, Value
from django.db.models.functions import Concat

from drf_spectacular.utils import extend_schema
from rest_framework import mixins, serializers, viewsets

from posthog.api.organization_member import organization_members_base_queryset
from posthog.api.routing import TeamAndOrgViewSetMixin
from posthog.helpers.trigram_search import MAX_SEARCH_LENGTH, normalize_search_term
from posthog.models import OrganizationMembership
from posthog.permissions import IsStaffUserOrImpersonating, PostHogFeatureFlagPermission

from products.customer_analytics.backend.facade.constants import CUSTOMER_ANALYTICS_CSP_FLAG
from products.customer_analytics.backend.presentation.views.serializers import AccountOrganizationMemberSerializer

DEFAULT_ORDERING = "-joined_at"
ALLOWED_ORDERINGS = frozenset({"joined_at", "-joined_at", "level", "-level", "last_login", "-last_login"})


# Excluded from the generated OpenAPI clients: this is an INTERNAL, staff-only endpoint
# consumed only by the customer-analytics Accounts UI via a handwritten api call (consistent
# with how the sibling organization-members endpoints are accessed).
@extend_schema(exclude=True)
class OrganizationMembersForAccountViewSet(
    TeamAndOrgViewSetMixin,
    mixins.ListModelMixin,
    viewsets.GenericViewSet,
):
    """Members of the organization given by `organization_id`. Read-only, internal."""

    scope_object = "INTERNAL"
    serializer_class = AccountOrganizationMemberSerializer
    permission_classes = [PostHogFeatureFlagPermission, IsStaffUserOrImpersonating]
    posthog_feature_flag = CUSTOMER_ANALYTICS_CSP_FLAG

    def dangerously_get_queryset(self) -> QuerySet:
        # Not scoped to the caller's org — the target org comes from the query param; the flag and is_staff gate access.
        organization_id = self.request.GET.get("organization_id")
        if not organization_id:
            return OrganizationMembership.objects.none()
        try:
            UUID(str(organization_id))
        except (ValueError, TypeError):
            return OrganizationMembership.objects.none()
        # Pagination needs a stable order. The default `-joined_at` is served by the
        # (organization, -joined_at) composite index when filtering by organization_id.
        queryset = (
            organization_members_base_queryset()
            .filter(organization_id=organization_id)
            .annotate(last_login=F("user__last_login"))
            .order_by(*self._ordering())
        )
        queryset = self._apply_levels_filter(queryset)
        search = self.request.query_params.get("search", "")
        if len(search) > MAX_SEARCH_LENGTH:
            raise serializers.ValidationError(
                {"search": f"Search query must be {MAX_SEARCH_LENGTH} characters or fewer."}
            )
        if normalized_search := normalize_search_term(search):
            return queryset.annotate(
                account_member_full_name=Concat("user__first_name", Value(" "), "user__last_name")
            ).filter(
                Q(user__first_name__icontains=normalized_search)
                | Q(user__last_name__icontains=normalized_search)
                | Q(user__email__icontains=normalized_search)
                | Q(account_member_full_name__icontains=normalized_search)
            )
        return queryset

    def _ordering(self) -> list:
        """Whitelisted `ordering` param, nulls-last for last_login, `-joined_at` as the tiebreaker."""
        ordering = self.request.query_params.get("ordering") or DEFAULT_ORDERING
        if ordering not in ALLOWED_ORDERINGS:
            raise serializers.ValidationError({"ordering": f"Must be one of: {', '.join(sorted(ALLOWED_ORDERINGS))}."})
        if ordering in ("joined_at", "-joined_at"):
            return [ordering]
        descending = ordering.startswith("-")
        field = F(ordering.lstrip("-"))
        primary = field.desc(nulls_last=True) if descending else field.asc(nulls_first=True)
        return [primary, DEFAULT_ORDERING]

    def _apply_levels_filter(self, queryset: QuerySet) -> QuerySet:
        levels_param = self.request.query_params.get("levels")
        if not levels_param:
            return queryset
        try:
            levels = [int(level) for level in levels_param.split(",") if level]
        except ValueError:
            raise serializers.ValidationError({"levels": "Must be a comma-separated list of integers."})
        return queryset.filter(level__in=levels)
