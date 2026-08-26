from uuid import UUID

from django.db.models import Q, QuerySet, Value
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
        # Ordering kept (not removed): pagination needs a stable, index-backed order; `-joined_at`
        # is served by the (organization, -joined_at) composite index when filtering by organization_id.
        queryset = organization_members_base_queryset().filter(organization_id=organization_id).order_by("-joined_at")
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
