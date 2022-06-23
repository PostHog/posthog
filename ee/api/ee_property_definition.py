from django.db.models import Prefetch
from rest_framework import serializers

from ee.models.property_definition import EnterprisePropertyDefinition
from posthog.api.property_definition import HIDDEN_PROPERTY_DEFINITIONS, PropertyDefinitionViewSet
from posthog.api.shared import UserBasicSerializer
from posthog.api.tagged_item import TaggedItemSerializerMixin
from posthog.constants import AvailableFeature
from posthog.models import TaggedItem
from posthog.models.property_definition import PropertyDefinition


class EnterprisePropertyDefinitionSerializer(TaggedItemSerializerMixin, serializers.ModelSerializer):
    updated_by = UserBasicSerializer(read_only=True)

    class Meta:
        model = EnterprisePropertyDefinition
        fields = (
            "id",
            "name",
            "description",
            "tags",
            "is_numerical",
            "updated_at",
            "updated_by",
            "query_usage_30_day",
            "is_event_property",
            "property_type",
        )
        read_only_fields = ["id", "name", "is_numerical", "query_usage_30_day", "is_event_property"]

    def update(self, event_definition: EnterprisePropertyDefinition, validated_data):
        validated_data["updated_by"] = self.context["request"].user
        return super().update(event_definition, validated_data)


class EnterprisePropertyDefinitionViewSet(PropertyDefinitionViewSet):
    serializer_class = EnterprisePropertyDefinitionSerializer

    def get_queryset(self):
        if self.request.user.organization.is_feature_available(AvailableFeature.INGESTION_TAXONOMY):  # type: ignore
            name_filter, name_params = self._get_name_filter()
            numerical_filter = self._get_numerical_filter()
            event_names = self._get_event_names()
            excluded_properties = self._get_excluded_properties()
            event_property_field, event_property_filter = self._get_event_property_field()
            search_query, search_params = self._get_search_fields()

            params = {
                "event_names": tuple(event_names or []),
                "names": name_params,
                "team_id": self.team_id,
                "excluded_properties": tuple(set.union(set(excluded_properties or []), HIDDEN_PROPERTY_DEFINITIONS)),
                **search_params,
            }

            # Prevent fetching deprecated `tags` field. Tags are separately fetched in TaggedItemSerializerMixin
            property_definition_fields = ", ".join(
                [f'"{f.column}"' for f in EnterprisePropertyDefinition._meta.get_fields() if hasattr(f, "column") and f.column != "tags"],  # type: ignore
            )

            return EnterprisePropertyDefinition.objects.raw(
                f"""
                            SELECT {property_definition_fields},
                                    {event_property_field} AS is_event_property
                            FROM ee_enterprisepropertydefinition
                            FULL OUTER JOIN posthog_propertydefinition ON posthog_propertydefinition.id=ee_enterprisepropertydefinition.propertydefinition_ptr_id
                            WHERE team_id = %(team_id)s AND name NOT IN %(excluded_properties)s
                                {name_filter} {numerical_filter} {search_query} {event_property_filter}
                            ORDER BY is_event_property DESC, query_usage_30_day DESC NULLS LAST, name ASC
                            """,
                params=params,
            ).prefetch_related(
                Prefetch("tagged_items", queryset=TaggedItem.objects.select_related("tag"), to_attr="prefetched_tags"),
            )
        else:
            return super().get_queryset()

    def get_object(self):
        if self.request.user.organization.is_feature_available(AvailableFeature.INGESTION_TAXONOMY):  # type: ignore
            id = self.kwargs["id"]
            enterprise_property = EnterprisePropertyDefinition.objects.filter(id=id).first()
            if enterprise_property:
                return enterprise_property
            non_enterprise_property = PropertyDefinition.objects.get(id=id)
            new_enterprise_property = EnterprisePropertyDefinition(
                propertydefinition_ptr_id=non_enterprise_property.id, description="",
            )
            new_enterprise_property.__dict__.update(non_enterprise_property.__dict__)
            new_enterprise_property.save()
            return new_enterprise_property
        else:
            return super().get_object()
