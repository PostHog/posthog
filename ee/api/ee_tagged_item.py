from django.db.models import Q
from rest_framework import serializers

from posthog.models import Tag


class EnterpriseTaggedItemSerializerMixin(serializers.Serializer):
    """
    Serializer that interacts with EnterpriseTaggedItem model
    """

    def get_tags(self, obj):
        return list(obj.tags.values_list("tag__name", flat=True)) if obj.tags else []

    def set_tags(self, tags, obj):
        if not obj:
            # If the object hasn't been created yet, this method will be called again on the create method.
            return

        # Create new tags
        for tag in tags:
            tag_instance, _ = Tag.objects.get_or_create(name=tag, team_id=obj.team_id)
            obj.tags.get_or_create(tag_id=tag_instance.id)

        # Delete tags that are missing
        obj.tags.exclude(tag__name__in=tags).delete()

        # Cleanup tags that aren't used by team
        Tag.objects.filter(Q(team_id=obj.team_id) & Q(taggeditems__isnull=True)).delete()
