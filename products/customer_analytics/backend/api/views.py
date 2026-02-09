from rest_framework import viewsets

from posthog.api.routing import TeamAndOrgViewSetMixin
from posthog.api.utils import log_activity_from_viewset

from products.customer_analytics.backend.models import CustomerJourney, CustomerProfileConfig

from .serializers import CustomerJourneySerializer, CustomerProfileConfigSerializer
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


class CustomerJourneyViewSet(TeamAndOrgViewSetMixin, viewsets.ModelViewSet):
    scope_object = "customer_journey"
    queryset = CustomerJourney.objects.order_by("order", "created_at").all()
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
