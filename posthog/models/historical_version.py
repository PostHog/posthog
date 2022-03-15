import datetime
import json

from django.db import models
from django.utils import timezone

from posthog.models import FeatureFlag
from posthog.models.utils import UUIDModel


class HistoricalVersionJSONEncoder(json.JSONEncoder):
    def default(self, obj):
        if isinstance(obj, models.base.ModelState):
            return None
        if isinstance(obj, FeatureFlag):
            return obj.__dict__
        if isinstance(obj, datetime.datetime):
            return obj.isoformat()

        return json.JSONEncoder.default(self, obj)


class HistoricalVersion(UUIDModel):
    """
     When calling delete lifecycle hooks in django rest framework
    (see "Save and deletion hooks" in https://www.django-rest-framework.org/api-guide/generic-views/)

    With Django Rest Framework you are not provided with the before and after states, so:
     * storing the before and after of the model
     * or computing and storing the change that occurs to the model
    would require complication or extra DB reads

    Django Rest Framework provides the state of the model _after_ the change.
    So, this history log stores that state and uses it to compute what changed
    when reading the history log
    (see history_logging.py for how change is computed)
    """

    class Action(models.TextChoices):
        Create = "create"
        Update = "update"
        Delete = "delete"

    class Meta:
        constraints = [
            models.CheckConstraint(
                check=models.Q(team_id__isnull=False) | models.Q(organization_id__isnull=False),
                name="must_have_team_or_organization_id",
            ),
        ]
        indexes = [
            models.Index(fields=["item_id", "team_id", "name"]),
        ]

    # JSON of the historical item
    state = models.JSONField(null=False, encoder=HistoricalVersionJSONEncoder)
    # e.g. FeatureFlags - in practice this will be the name of a model class
    name = models.fields.CharField(max_length=79, null=False)

    action = models.CharField(max_length=6, choices=Action.choices, blank=True, null=False)

    # the id of the item being versioned
    # this might be a numerical id, short id, or UUID, so each will be converted to string
    # it will be used to lookup rows with exactly matching item_ids
    # it probably only needs to be 36 characters in order to hold a GUID
    # but 72 may be useful to avoid a migration in future
    item_id = models.fields.CharField(max_length=72, null=False)

    # to avoid an integer version field for ordering revisions
    versioned_at: models.DateTimeField = models.DateTimeField(default=timezone.now)

    created_by = models.ForeignKey("posthog.User", null=True, on_delete=models.SET_NULL)

    # team or organization that contains the change not every item that might be versioned has a team id
    team_id = models.PositiveIntegerField(null=True)
    organization_id = models.UUIDField(null=True)

    @staticmethod
    def save_version(serializer, action: str) -> None:
        HistoricalVersion.objects.create(
            state=serializer.data,
            name=serializer.instance.__class__.__name__,
            item_id=serializer.instance.id,
            action=action,
            created_by=serializer.context["request"].user,
            team_id=serializer.context["team_id"],
        )

    @staticmethod
    def save_deletion(instance, item_id: int, team_id: int, user) -> None:
        HistoricalVersion.objects.create(
            state=instance,
            name=instance.__class__.__name__,
            action="delete",
            item_id=item_id,
            created_by=user,
            team_id=team_id,
        )
