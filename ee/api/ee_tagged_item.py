from typing import Dict

from rest_framework import serializers

from posthog.models.tagged_item import EnterpriseTaggedItem


class EnterpriseTaggedItemSerializerMixin(serializers.Serializer):
    """
    Serializer that interacts with EnterpriseTaggedItem model
    """

    def get_tags(self, obj):
        return list(obj.tags.values_list("tag", flat=True)) if obj.tags else []

    def set_tags(self, tags, obj):
        if not obj:
            # If the object hasn't been created yet, this method will be called again on the create method.
            return

        # Create new tags
        for tag in tags:
            obj.tags.get_or_create(tag=tag, team_id=obj.team_id)

        # Delete tags that are missing
        obj.tags.exclude(tag__in=tags).delete()
