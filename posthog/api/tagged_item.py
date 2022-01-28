from rest_framework import serializers

from posthog.api.utils import WritableSerializerMethodField
from posthog.constants import AvailableFeature
from posthog.exceptions import EnterpriseFeatureException


class TaggedItemSerializerMixin(serializers.Serializer):
    tags = WritableSerializerMethodField(required=False)
    tags_v2 = WritableSerializerMethodField(required=False)

    def get_tags_v2(self, obj):
        if self.context["request"].user.organization.is_feature_available(AvailableFeature.INGESTION_TAXONOMY):
            try:
                from ee.api.ee_tagged_item import EnterpriseTaggedItemSerializerMixin
            except ImportError:
                pass
            else:
                return EnterpriseTaggedItemSerializerMixin(self).get_tags_v2(obj)
        return []

    def set_tags_v2(self, tags, obj):
        if self.context["request"].user.organization.is_feature_available(AvailableFeature.INGESTION_TAXONOMY):
            try:
                from ee.api.ee_tagged_item import EnterpriseTaggedItemSerializerMixin
            except ImportError:
                pass
            else:
                EnterpriseTaggedItemSerializerMixin(self).set_tags_v2(tags, obj)
                return
        raise EnterpriseFeatureException()

    # Below methods are getters and setters for legacy `tag` that make serializers that inherit this mixin backwards
    # compatible.

    # On fetching legacy `tags`, insert old tags into new tags table if it doesn't already exist.
    def get_tags(self, obj):
        if self.context["request"].user.organization.is_feature_available(AvailableFeature.INGESTION_TAXONOMY):
            try:
                from ee.api.ee_tagged_item import EnterpriseTaggedItemSerializerMixin
            except ImportError:
                pass
            else:
                return EnterpriseTaggedItemSerializerMixin(self).migrate_and_get_tags(obj)
        return []

    # Intercept setting new tags to use tags_v2. Old tags column will no longer be updated
    def set_tags(self, tags, obj):
        if self.context["request"].user.organization.is_feature_available(AvailableFeature.INGESTION_TAXONOMY):
            try:
                from ee.api.ee_tagged_item import EnterpriseTaggedItemSerializerMixin
            except ImportError:
                pass
            else:
                EnterpriseTaggedItemSerializerMixin(self).set_tags_v2(tags, obj)
                return
        raise EnterpriseFeatureException()
