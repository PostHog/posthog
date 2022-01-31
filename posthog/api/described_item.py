from rest_framework import serializers

from posthog.api.utils import WritableSerializerMethodField
from posthog.constants import AvailableFeature
from posthog.exceptions import EnterpriseFeatureException


class DescribedItemSerializerMixin(serializers.Serializer):
    """
    Serializer mixin that aliases description -> global_description and determines appropriate response depending on license.
    """

    description = WritableSerializerMethodField(required=False)

    def get_description(self, obj):
        if (
            "request" in self.context
            and not self.context["request"].user.is_anonymous
            and self.context["request"].user.organization.is_feature_available(AvailableFeature.INGESTION_TAXONOMY)
        ):
            try:
                from ee.api.ee_described_item import EnterpriseDescribedItemSerializerMixin
            except ImportError:
                pass
            else:
                return EnterpriseDescribedItemSerializerMixin(self).get_description(obj)
        return None

    def set_description(self, description, obj):
        if (
            "request" in self.context
            and not self.context["request"].user.is_anonymous
            and self.context["request"].user.organization.is_feature_available(AvailableFeature.INGESTION_TAXONOMY)
        ):
            try:
                from ee.api.ee_described_item import EnterpriseDescribedItemSerializerMixin
            except ImportError:
                pass
            else:
                EnterpriseDescribedItemSerializerMixin(self).set_description(description, obj)
                return
        # Reject setting description if non ee
        if description:
            raise EnterpriseFeatureException()
