from rest_framework import viewsets

from posthog.api.routing import TeamAndOrgViewSetMixin

from products.customer_analytics.backend.models import CustomerProfileConfig

from .serializers import CustomerProfileConfigSerializer
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
