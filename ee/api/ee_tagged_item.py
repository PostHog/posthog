from rest_framework import serializers

from posthog.models.tagged_item import EnterpriseTaggedItem


class EnterpriseTaggedItemSerializerMixin(serializers.Serializer):
    """
    Serializer that interacts with EnterpriseTaggedItem model
    """

    def get_tags_v2(self, obj):

        return list(obj.tags.all())

    def set_tags_v2(self, obj):
        return list(obj.tags.all())
