from rest_framework import serializers

from posthog.models.described_item import EnterpriseDescribedItem


class EnterpriseDescribedItemSerializerMixin(serializers.Serializer):
    """
    Serializer mixin that interacts with EnterpriseDescribedItem model
    """

    def get_description(self, obj):
        described_item = obj.global_description.all().first()
        return described_item.description if described_item else None

    def set_description(self, description, obj):
        if not obj:
            return

        # There can only be at most one description per instance at a time.
        obj.global_description.all().delete()
        EnterpriseDescribedItem.objects.create(content_object=obj, team_id=obj.team_id, description=description)
