import json

from drf_spectacular.utils import OpenApiParameter, OpenApiTypes, extend_schema
from rest_framework import viewsets

from posthog.api.routing import TeamAndOrgViewSetMixin
from posthog.api.tagged_item import TaggedItemViewSetMixin
from posthog.api.utils import log_activity_from_viewset
from posthog.rbac.access_control_api_mixin import AccessControlViewSetMixin

from products.customer_analytics.backend.models import Account, CustomerJourney, CustomerProfileConfig

from .serializers import AccountSerializer, CustomerJourneySerializer, CustomerProfileConfigSerializer
from .utils import log_customer_profile_config_activity


class CustomerProfileConfigViewSet(TeamAndOrgViewSetMixin, viewsets.ModelViewSet):
    scope_object = "customer_profile_config"
    queryset = CustomerProfileConfig.objects.all()
    serializer_class = CustomerProfileConfigSerializer

    def perform_create(self, serializer):
        instance = serializer.save()
        log_customer_profile_config_activity(viewset=self, instance=instance, activity="created")

    def perform_update(self, serializer):
        previous_instance = CustomerProfileConfig.objects.get(pk=serializer.instance.pk)
        instance = serializer.save()
        log_customer_profile_config_activity(
            viewset=self, instance=instance, activity="updated", previous=previous_instance
        )

    def perform_destroy(self, instance):
        instance_id = instance.id
        instance_scope = instance.scope

        super().perform_destroy(instance)

        temp_instance = CustomerProfileConfig(id=instance_id, scope=instance_scope)
        log_customer_profile_config_activity(viewset=self, instance=temp_instance, activity="deleted")


class CustomerJourneyViewSet(TeamAndOrgViewSetMixin, AccessControlViewSetMixin, viewsets.ModelViewSet):
    scope_object = "customer_journey"
    queryset = CustomerJourney.objects.order_by("created_at").all()
    serializer_class = CustomerJourneySerializer

    def safely_get_queryset(self, queryset):
        return queryset.filter(team_id=self.team.id)

    def perform_create(self, serializer):
        serializer.save()
        log_activity_from_viewset(self, serializer.instance, name=serializer.instance.name)

    def perform_update(self, serializer):
        previous = self.get_object()
        serializer.save()
        log_activity_from_viewset(self, serializer.instance, name=serializer.instance.name, previous=previous)

    def perform_destroy(self, instance):
        log_activity_from_viewset(self, instance, activity="deleted", name=instance.name)
        super().perform_destroy(instance)


@extend_schema(tags=["customer_analytics"])
class AccountViewSet(TaggedItemViewSetMixin, TeamAndOrgViewSetMixin, AccessControlViewSetMixin, viewsets.ModelViewSet):
    scope_object = "account"
    queryset = Account.objects.unscoped().order_by("-created_at")
    serializer_class = AccountSerializer
    bulk_update_tags = None  # Mixin action assumes integer PKs; Account uses UUIDs.

    ROLE_FILTER_FIELDS = ("csm", "account_executive", "account_owner")
    ALLOWED_ORDERING = frozenset({"name", "-name", "created_at", "-created_at", "updated_at", "-updated_at"})

    @extend_schema(
        parameters=[
            OpenApiParameter(
                name="tags",
                type=OpenApiTypes.STR,
                location=OpenApiParameter.QUERY,
                required=False,
                description=(
                    'JSON-encoded array of tag names to filter by, e.g. `["enterprise","priority"]`. '
                    "Returns accounts that have any of the listed tags."
                ),
            ),
            OpenApiParameter(
                name="csm",
                type=OpenApiTypes.STR,
                location=OpenApiParameter.QUERY,
                required=False,
                description=("Filter by CSM. Use 'unassigned' for accounts with no CSM, or an integer user id."),
            ),
            OpenApiParameter(
                name="account_executive",
                type=OpenApiTypes.STR,
                location=OpenApiParameter.QUERY,
                required=False,
                description="Filter by account executive. Use 'unassigned' or an integer user id.",
            ),
            OpenApiParameter(
                name="account_owner",
                type=OpenApiTypes.STR,
                location=OpenApiParameter.QUERY,
                required=False,
                description="Filter by account owner. Use 'unassigned' or an integer user id.",
            ),
            OpenApiParameter(
                name="all_roles_unassigned",
                type=OpenApiTypes.BOOL,
                location=OpenApiParameter.QUERY,
                required=False,
                description=(
                    "When true, returns only accounts where CSM, account executive, and account owner are all unset."
                ),
            ),
            OpenApiParameter(
                name="ordering",
                type=OpenApiTypes.STR,
                location=OpenApiParameter.QUERY,
                required=False,
                enum=["name", "-name", "created_at", "-created_at", "updated_at", "-updated_at"],
                description="Sort order. Defaults to '-created_at'.",
            ),
        ],
    )
    def list(self, request, *args, **kwargs):
        return super().list(request, *args, **kwargs)

    def safely_get_queryset(self, queryset):
        queryset = queryset.filter(team_id=self.team.id)

        tags_param = self.request.query_params.get("tags")
        if tags_param:
            try:
                tags_list = json.loads(tags_param)
                if isinstance(tags_list, list) and tags_list:
                    queryset = queryset.filter(tagged_items__tag__name__in=tags_list).distinct()
            except json.JSONDecodeError:
                pass

        # An unset role is serialized as JSON null, which `_properties__role__isnull`
        # does not match; probing the nested `id` matches every unassigned
        # representation (missing key, null value, or empty object).
        if self.request.query_params.get("all_roles_unassigned", "").lower() == "true":
            queryset = queryset.filter(
                _properties__csm__id__isnull=True,
                _properties__account_executive__id__isnull=True,
                _properties__account_owner__id__isnull=True,
            )

        for role_field in self.ROLE_FILTER_FIELDS:
            value = self.request.query_params.get(role_field)
            if not value:
                continue
            if value == "unassigned":
                queryset = queryset.filter(**{f"_properties__{role_field}__id__isnull": True})
            else:
                try:
                    user_id = int(value)
                except ValueError:
                    continue
                queryset = queryset.filter(**{f"_properties__{role_field}__id": user_id})

        ordering = self.request.query_params.get("ordering")
        if ordering in self.ALLOWED_ORDERING:
            queryset = queryset.order_by(ordering)

        return queryset

    def perform_create(self, serializer):
        serializer.save()
        log_activity_from_viewset(self, serializer.instance, name=serializer.instance.name)

    def perform_update(self, serializer):
        previous = self.get_object()
        serializer.save()
        log_activity_from_viewset(self, serializer.instance, name=serializer.instance.name, previous=previous)

    def perform_destroy(self, instance):
        log_activity_from_viewset(self, instance, activity="deleted", name=instance.name)
        super().perform_destroy(instance)
