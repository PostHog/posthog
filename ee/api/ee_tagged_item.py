from django.db.models import Prefetch, Q
from rest_framework import serializers, viewsets

from posthog.models import Tag, TaggedItem


class EnterpriseTaggedItemSerializerMixin(serializers.Serializer):
    """
    Serializer that interacts with TaggedItem model
    """

    def get_tags(self, obj):
        if hasattr(obj, "prefetched_tags"):
            return [p.tag.name for p in obj.prefetched_tags]
        return list(obj.tagged_items.values_list("tag__name", flat=True)) if obj.tags else []

    def set_tags(self, tags, obj):
        if not obj:
            # If the object hasn't been created yet, this method will be called again on the create method.
            return

        # Normalize and dedupe tags
        deduped_tags = list(set([t.strip().lower() for t in tags]))
        tagged_item_objects = []

        # Create tags
        for tag in deduped_tags:
            tag_instance, _ = Tag.objects.get_or_create(name=tag, team_id=obj.team_id)
            tagged_item_instance, _ = obj.tagged_items.get_or_create(tag_id=tag_instance.id)
            tagged_item_objects.append(tagged_item_instance)

        # Delete tags that are missing
        obj.tags.exclude(tag__name__in=deduped_tags).delete()

        # Cleanup tags that aren't used by team
        Tag.objects.filter(Q(team_id=obj.team_id) & Q(tagged_items__isnull=True)).delete()

        obj.prefetched_tags = tagged_item_objects
