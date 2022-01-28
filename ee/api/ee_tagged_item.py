from rest_framework import serializers

from posthog.models.tagged_item import EnterpriseTaggedItem


class EnterpriseTaggedItemSerializerMixin(serializers.Serializer):
    """
    Serializer that interacts with EnterpriseTaggedItem model
    """

    def _sync_tags(self, tags, obj, read_only=True):
        # Create new tags
        for tag in tags:
            existing_tag = obj.tags_v2.filter(tag=tag, team_id=obj.team_id)
            if not existing_tag:
                new_tag = EnterpriseTaggedItem(content_object=obj, tag=tag, team_id=obj.team_id)
                new_tag.save()

        if not read_only:
            # Delete tags that are missing
            obj.tags_v2.exclude(tag__in=tags).delete()

    def get_tags_v2(self, obj):
        return list(obj.tags_v2.values_list("tag", flat=True)) if obj.tags_v2 else []

    def set_tags_v2(self, tags, obj):
        if not obj:
            return

        self._sync_tags(tags, obj, False)

    def migrate_and_get_tags(self, obj):
        tags = obj.tags or []
        self._sync_tags(tags, obj)

        return list(obj.tags_v2.values_list("tag", flat=True))
