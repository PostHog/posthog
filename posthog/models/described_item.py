from django.contrib.contenttypes.fields import GenericForeignKey
from django.contrib.contenttypes.models import ContentType
from django.db import models

from posthog.models.utils import UUIDModel


class EnterpriseDescribedItem(UUIDModel):
    """
    Describes global description-object relationships.
    Note: This is an EE only feature, however the model exists in posthog so that it is backwards accessible from all
    models. Whether we should be able to interact with this table is determined in the `DescribedItemSerializer` which
    imports `EnterpriseDescribedItemSerializer` if the feature is available.

    There are many models that already have description fields (dashboard, insight, etc.), but a few of these are ee
    only features (part of taxonomy) that should have been refactored out into the ee/ folder. Eventually we'll want to
    use EnterpriseDescribedItem for all descriptions app-wide.

    Models that had in-line description fields before this table was created:
    - models/cohort.py
    - models/dashboard.py
    - models/insight.py
    - ee/models/event_definition.py
    - ee/models/property_definition.py

    Models that are describable via this model:
    - models/action.py
    - models/cohort.py                  TODO: refactor to use this model
    - models/dashboard.py               TODO: refactor to use this model
    - models/insight.py                 TODO: refactor to use this model
    - ee/models/event_definition.py     TODO: refactor to use this model
    - ee/models/property_definition.py  TODO: refactor to use this model
    """

    description: models.TextField = models.TextField(blank=True)
    team: models.ForeignKey = models.ForeignKey("Team", on_delete=models.CASCADE)

    content_type: models.ForeignKey = models.ForeignKey(ContentType, on_delete=models.CASCADE)
    # Primary key value of related model. Query by this to get all tags for specific model. This is a charfield because
    # there we don't have a standard way of storing objects. Some models use positive integer ids and others use UUID's.
    object_id: models.CharField = models.CharField(max_length=400)
    content_object: GenericForeignKey = GenericForeignKey("content_type", "object_id")

    class Meta:
        unique_together = ("content_type", "object_id")

    def __str__(self):
        return self.description
