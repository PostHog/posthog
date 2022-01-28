from rest_framework import serializers

from posthog.models.tagged_item import EnterpriseTaggedItem


class EnterpriseTaggedItemSerializerMixin(serializers.Serializer):
    """
    Serializer that interacts with EnterpriseTaggedItem model
    """

    def get_global_tags(self, obj):
        return list(obj.global_tags.values_list("tag", flat=True)) if obj.global_tags else []

    def set_global_tags(self, tags, obj):
        if not obj:
            return

        # Create new tags
        for tag in tags:
            existing_tag = obj.global_tags.filter(tag=tag, team_id=obj.team_id)
            if not existing_tag:
                EnterpriseTaggedItem.objects.create(content_object=obj, tag=tag, team_id=obj.team_id)

        # Delete tags that are missing
        obj.global_tags.exclude(tag__in=tags).delete()
