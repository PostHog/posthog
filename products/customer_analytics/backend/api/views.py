import json

from django.db import transaction
from django.db.models import Prefetch, Q
from django.shortcuts import get_object_or_404

from drf_spectacular.types import OpenApiTypes
from drf_spectacular.utils import OpenApiParameter, extend_schema
from rest_framework import mixins, viewsets
from rest_framework.exceptions import ValidationError

from posthog.api.routing import TeamAndOrgViewSetMixin
from posthog.api.tagged_item import TaggedItemViewSetMixin
from posthog.api.utils import log_activity_from_viewset
from posthog.rbac.access_control_api_mixin import AccessControlViewSetMixin

from products.customer_analytics.backend.models import Account, CustomerJourney, CustomerProfileConfig
from products.notebooks.backend.models import Notebook, ResourceNotebook

from .serializers import (
    AccountNotebookSerializer,
    AccountSerializer,
    CustomerJourneySerializer,
    CustomerProfileConfigSerializer,
)
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

    ALLOWED_ORDERING = frozenset({"name", "-name", "created_at", "-created_at", "updated_at", "-updated_at"})

    @extend_schema(
        parameters=[
            OpenApiParameter(
                name="search",
                type=OpenApiTypes.STR,
                location=OpenApiParameter.QUERY,
                required=False,
                description="Case-insensitive substring search across account name and external ID.",
            ),
            OpenApiParameter(
                name="tags",
                type=OpenApiTypes.STR,
                location=OpenApiParameter.QUERY,
                required=False,
                description=(
                    'JSON-encoded array of tag names to filter by, e.g. `["enterprise","priority"]`. '
                    "Returns accounts that have any of the listed tags. "
                    "Malformed values (not a JSON-encoded list of strings) return a 400."
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
        queryset = queryset.filter(team_id=self.team.id).prefetch_related(
            Prefetch("notebooks", queryset=ResourceNotebook.objects.select_related("notebook"))
        )

        search = self.request.query_params.get("search", "").strip()
        if search:
            queryset = queryset.filter(Q(name__icontains=search) | Q(external_id__icontains=search))

        tags_param = self.request.query_params.get("tags")
        if tags_param:
            try:
                tags_list = json.loads(tags_param)
            except json.JSONDecodeError:
                raise ValidationError({"tags": "Must be a JSON-encoded list of strings."})
            if not isinstance(tags_list, list) or not all(isinstance(t, str) for t in tags_list):
                raise ValidationError({"tags": "Must be a JSON-encoded list of strings."})
            if tags_list:
                queryset = queryset.filter(tagged_items__tag__name__in=tags_list).distinct()

        # An unset role is serialized as JSON null, which `_properties__role__isnull`
        # does not match; probing the nested `id` matches every unassigned
        # representation (missing key, null value, or empty object).
        if self.request.query_params.get("all_roles_unassigned", "").lower() == "true":
            queryset = queryset.filter(
                _properties__csm__id__isnull=True,
                _properties__account_executive__id__isnull=True,
                _properties__account_owner__id__isnull=True,
            )

        csm_value = self.request.query_params.get("csm")
        if csm_value == "unassigned":
            queryset = queryset.filter(_properties__csm__id__isnull=True)
        elif csm_value:
            try:
                queryset = queryset.filter(_properties__csm__id=int(csm_value))
            except ValueError:
                pass

        ae_value = self.request.query_params.get("account_executive")
        if ae_value == "unassigned":
            queryset = queryset.filter(_properties__account_executive__id__isnull=True)
        elif ae_value:
            try:
                queryset = queryset.filter(_properties__account_executive__id=int(ae_value))
            except ValueError:
                pass

        owner_value = self.request.query_params.get("account_owner")
        if owner_value == "unassigned":
            queryset = queryset.filter(_properties__account_owner__id__isnull=True)
        elif owner_value:
            try:
                queryset = queryset.filter(_properties__account_owner__id=int(owner_value))
            except ValueError:
                pass

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


@extend_schema(
    tags=["customer_analytics"],
    parameters=[
        OpenApiParameter(
            name="account_id",
            type=OpenApiTypes.UUID,
            location=OpenApiParameter.PATH,
            description="UUID of the parent account.",
        ),
    ],
)
class AccountNotebookViewSet(
    TeamAndOrgViewSetMixin,
    AccessControlViewSetMixin,
    mixins.CreateModelMixin,
    mixins.ListModelMixin,
    mixins.RetrieveModelMixin,
    mixins.DestroyModelMixin,
    viewsets.GenericViewSet,
):
    scope_object = "account"
    serializer_class = AccountNotebookSerializer
    queryset = Notebook.objects.all()
    lookup_field = "short_id"
    filter_rewrite_rules = {"account_id": "resources__account_id"}

    def _get_account(self) -> Account:
        queryset = self.user_access_control.filter_queryset_by_access_level(
            Account.objects.unscoped().filter(team_id=self.team.id),
        )
        return get_object_or_404(queryset, id=self.parents_query_dict["account_id"])

    def safely_get_queryset(self, queryset):
        self._get_account()
        return (
            queryset.filter(deleted=False, visibility=Notebook.Visibility.INTERNAL)
            .select_related("created_by", "last_modified_by")
            .order_by("-last_modified_at")
        )

    @transaction.atomic
    def perform_create(self, serializer):
        account = self._get_account()
        notebook = serializer.save(
            team=self.team,
            created_by=self.request.user,
            last_modified_by=self.request.user,
            visibility=Notebook.Visibility.INTERNAL,
        )
        ResourceNotebook.objects.create(notebook=notebook, account=account)

    @transaction.atomic
    def perform_destroy(self, instance: Notebook):
        instance.delete()
