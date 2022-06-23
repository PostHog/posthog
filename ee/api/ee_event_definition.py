from django.db.models import Prefetch
from django.utils import timezone
from rest_framework import serializers

from ee.models.event_definition import EnterpriseEventDefinition
from posthog.api.event_definition import EventDefinitionViewSet
from posthog.api.shared import UserBasicSerializer
from posthog.api.tagged_item import TaggedItemSerializerMixin
from posthog.api.utils import create_event_definitions_sql
from posthog.constants import AvailableFeature
from posthog.filters import term_search_filter_sql
from posthog.models import TaggedItem
from posthog.models.event_definition import EventDefinition


class EnterpriseEventDefinitionSerializer(TaggedItemSerializerMixin, serializers.ModelSerializer):
    updated_by = UserBasicSerializer(read_only=True)
    verified_by = UserBasicSerializer(read_only=True)
    created_by = UserBasicSerializer(read_only=True)
    is_action = serializers.SerializerMethodField(read_only=True)
    action_id = serializers.IntegerField(read_only=True)
    is_calculating = serializers.BooleanField(read_only=True)
    last_calculated_at = serializers.DateTimeField(read_only=True)
    post_to_slack = serializers.BooleanField(default=False)

    class Meta:
        model = EnterpriseEventDefinition
        fields = (
            "id",
            "name",
            "owner",
            "description",
            "tags",
            "volume_30_day",
            "query_usage_30_day",
            "created_at",
            "updated_at",
            "updated_by",
            "last_seen_at",
            "verified",
            "verified_at",
            "verified_by",
            # Action fields
            "is_action",
            "action_id",
            "is_calculating",
            "last_calculated_at",
            "created_by",
            "post_to_slack",
        )
        read_only_fields = [
            "id",
            "name",
            "created_at",
            "updated_at",
            "volume_30_day",
            "query_usage_30_day",
            "last_seen_at",
            "verified_at",
            "verified_by",
            # Action fields
            "is_action",
            "action_id",
            "is_calculating",
            "last_calculated_at",
            "created_by",
        ]

    def update(self, event_definition: EnterpriseEventDefinition, validated_data):
        validated_data["updated_by"] = self.context["request"].user

        if "verified" in validated_data:
            if validated_data["verified"] and not event_definition.verified:
                # Verify event only if previously unverified
                validated_data["verified_by"] = self.context["request"].user
                validated_data["verified_at"] = timezone.now()
                validated_data["verified"] = True
            elif not validated_data["verified"]:
                # Unverifying event nullifies verified properties
                validated_data["verified_by"] = None
                validated_data["verified_at"] = None
                validated_data["verified"] = False
            else:
                # Attempting to re-verify an already verified event, invalid action. Ignore attribute.
                validated_data.pop("verified")

        return super().update(event_definition, validated_data)

    def to_representation(self, instance):
        representation = super().to_representation(instance)
        representation["owner"] = (
            UserBasicSerializer(instance=instance.owner).data if hasattr(instance, "owner") and instance.owner else None
        )
        return representation

    def get_is_action(self, obj):
        return hasattr(obj, "action_id") and obj.action_id is not None


class EnterpriseEventDefinitionViewSet(EventDefinitionViewSet):
    serializer_class = EnterpriseEventDefinitionSerializer

    def get_queryset(self):

        if self.request.user.organization.is_feature_available(AvailableFeature.INGESTION_TAXONOMY):  # type: ignore
            # `include_actions`
            #   If true, return both list of event definitions and actions together.
            include_actions = self.request.GET.get("include_actions", None) == "true"

            search = self.request.GET.get("search", None)
            search_query, search_kwargs = term_search_filter_sql(self.search_fields, search)

            params = {
                "team_id": self.team_id,
                **search_kwargs,
            }

            # Prevent fetching deprecated `tags` field. Tags are separately fetched in TaggedItemSerializerMixin
            sql = create_event_definitions_sql(include_actions, is_enterprise=True, conditions=search_query)

            ee_event_definitions = EnterpriseEventDefinition.objects.raw(sql, params=params)
            ee_event_definitions_list = ee_event_definitions.prefetch_related(
                Prefetch("tagged_items", queryset=TaggedItem.objects.select_related("tag"), to_attr="prefetched_tags")
            )

            return ee_event_definitions_list
        else:
            return super().get_queryset()

    def get_object(self):
        if self.request.user.organization.is_feature_available(AvailableFeature.INGESTION_TAXONOMY):  # type: ignore
            id = self.kwargs["id"]

            enterprise_event = EnterpriseEventDefinition.objects.filter(id=id).first()
            if enterprise_event:
                return enterprise_event

            non_enterprise_event = EventDefinition.objects.get(id=id)
            new_enterprise_event = EnterpriseEventDefinition(
                eventdefinition_ptr_id=non_enterprise_event.id, description=""
            )
            new_enterprise_event.__dict__.update(non_enterprise_event.__dict__)
            new_enterprise_event.save()
            return new_enterprise_event
        else:
            return super().get_object()
