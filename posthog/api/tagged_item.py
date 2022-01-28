from rest_framework import serializers

from posthog.api.utils import WritableSerializerMethodField
from posthog.constants import AvailableFeature
from posthog.exceptions import EnterpriseFeatureException


class TaggedItemSerializerMixin(serializers.Serializer):
    """
    Serializer mixin that aliases tags -> global_tags and determines appropriate response depending on license.
    """

    tags = WritableSerializerMethodField(required=False)

    def get_tags(self, obj):
        if self.context["request"].user.organization.is_feature_available(AvailableFeature.INGESTION_TAXONOMY):
            try:
                from ee.api.ee_tagged_item import EnterpriseTaggedItemSerializerMixin
            except ImportError:
                pass
            else:
                return EnterpriseTaggedItemSerializerMixin(self).get_global_tags(obj)
        return []

    def set_tags(self, tags, obj):
        if self.context["request"].user.organization.is_feature_available(AvailableFeature.INGESTION_TAXONOMY):
            try:
                from ee.api.ee_tagged_item import EnterpriseTaggedItemSerializerMixin
            except ImportError:
                pass
            else:
                EnterpriseTaggedItemSerializerMixin(self).set_global_tags(tags, obj)
                return
        raise EnterpriseFeatureException()
