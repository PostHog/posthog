import types
from pprint import pprint

from rest_framework import serializers

# from ee.clickhouse.views.groups import GroupSerializer
# from posthog.models import Dashboard, EventDefinition, PropertyDefinition, FeatureFlag, Cohort, Group, Organization, \
#     Insight
#
# import posthog.api as api
# from posthog.api.dashboard import DashboardSerializer
# from posthog.api.event_definition import EventDefinitionSerializer
# from posthog.api.feature_flag import FeatureFlagSerializer
# from posthog.api.insight import InsightSerializer
# from posthog.api.organization import OrganizationSerializer
# from posthog.api.property_definition import PropertyDefinitionSerializer
from posthog.constants import AvailableFeature
from posthog.exceptions import EnterpriseFeatureException
from posthog.models.tagged_item import EnterpriseTaggedItem


class WritableSerializerMethodField(serializers.SerializerMethodField):
    def __init__(self, method_name=None, **kwargs):
        self.method_name = method_name
        self.setter_method_name = kwargs.pop("setter_method_name", None)
        self.deserializer_field = kwargs.pop("deserializer_field")

        kwargs["source"] = "*"
        super(serializers.SerializerMethodField, self).__init__(**kwargs)

    def bind(self, field_name, parent):
        retval = super().bind(field_name, parent)
        if not self.setter_method_name:
            self.setter_method_name = f"set_{field_name}"

        return retval

    def to_internal_value(self, data):
        value = self.deserializer_field.to_internal_value(data)
        method = getattr(self.parent, self.setter_method_name)
        method(value)
        return {}


class TaggedItemSerializerMixin(serializers.Serializer):
    tags_v2 = WritableSerializerMethodField(deserializer_field=serializers.SlugField)

    def get_tags_v2(self, obj):
        if self.context["request"].user.organization.is_feature_available(AvailableFeature.INGESTION_TAXONOMY):
            try:
                from ee.api.ee_tagged_item import EnterpriseTaggedItemSerializerMixin
            except ImportError:
                pass
            else:
                return EnterpriseTaggedItemSerializerMixin(self).get_tags_v2(obj)
        return []

    def set_tags_v2(self, value):
        if self.context["request"].user.organization.is_feature_available(AvailableFeature.INGESTION_TAXONOMY):
            try:
                from ee.api.ee_tagged_item import EnterpriseTaggedItemSerializerMixin
            except ImportError:
                pass
            else:
                return EnterpriseTaggedItemSerializerMixin(self).get_tags_v2(value)
        raise EnterpriseFeatureException()


#
# class TaggedObjectRelatedField(serializers.RelatedField):
#
#     def __init__(self, **kwargs):
#         super(TaggedObjectRelatedField, self).__init__(**kwargs)
#
#     def to_representation(self, value):
#
#         print("BLAH", value)
#
#         if isinstance(value, Dashboard):
#             serializer = api.dashboard.DashboardSerializer(value)
#         elif isinstance(value, EventDefinition):
#             serializer = api.event_definition.EventDefinitionSerializer(value)
#         elif isinstance(value, PropertyDefinition):
#             serializer = api.property_definition.PropertyDefinitionSerializer(value)
#         elif isinstance(value, FeatureFlag):
#             serializer = api.feature_flag.FeatureFlagSerializer(value)
#         elif isinstance(value, Cohort):
#             serializer = api.cohort.CohortSerializer(value)
#         elif isinstance(value, Group):
#             serializer = GroupSerializer(value)
#         elif isinstance(value, Organization):
#             serializer = api.organization.OrganizationSerializer(value)
#         elif isinstance(value, Insight):
#             serializer = api.insight.InsightSerializer(value)
#         else:
#             raise Exception('Unexpected type of tagged object')
#
#         return serializer.data
#
#     def to_internal_value(self, data):
#         print("BLAH INTERNAL", data)
#         return None
#
#
# class TaggedItemSerializerMixin(serializers.ModelSerializer):
#     tags = serializers.SerializerMethodField()
#
