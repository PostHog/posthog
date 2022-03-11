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
    There are two ways to capture the history of changes to a thing

    1) capture the changes as they occur

    -> created flag with key blah
    -> changed name from "" to "something"
    -> set flag percentage to 25%
    -> etc

    With that set of changes you can start from item 0
    and read each change (left fold in functional language) to create the current state

    That isn't necessary as django stores the current state of the models for us

    Or you can start with the current state and apply the reverse of each change
    reading backwards over the set (right fold in functional language)
    to build the state at a given moment in time

    This makes showing the list of changes trivial. You would simply load (a page of) the list

    2) capture the state after the change at the time changes occur

    (you can capture the state before and after a change)

    -> created with state {"stuff": "here"}
    -> changed with state {"stuff": "here"}
    -> changed with state {"stuff": "here"}
    -> changed with state {"stuff": "here"}
    -> deleted with state {"stuff": "here"}

    With that stream of changes you can get the current state by reading the most recent item

    That isn't necessary as django stores the current state of the models for us

    Or you can directly read the state at a particular time

    In order to show the list of changes you have to read (a page of) the list of states
    and compute the change by comparing them

    ## How to choose between them

    When calling delete lifecycle hooks in django rest framework
    (see "Save and deletion hooks" in https://www.django-rest-framework.org/api-guide/generic-views/)

    You are not provided with the before and after states, so storing before and after
    or computing and storing the change would require complication or extra DB reads

    -> it is simpler in this context to store the state and compute changes later
    (see history_logging.py for the change computation)

    """

    class Action(models.TextChoices):
        Create = "create"
        Update = "update"
        Delete = "delete"

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["organization_id", "team_id", "name", "versioned_at"], name="unique_version"
            ),
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
        HistoricalVersion(
            state=serializer.data,
            name=serializer.instance.__class__.__name__,
            item_id=serializer.instance.id,
            action=action,
            created_by=serializer.context["request"].user,
            team_id=serializer.context["team_id"],
        ).save()

    @staticmethod
    def save_deletion(instance, item_id: int, team_id: int, user) -> None:
        version = HistoricalVersion(
            state=instance,
            name=instance.__class__.__name__,
            action="delete",
            item_id=item_id,
            created_by=user,
            team_id=team_id,
        )
        version.save()


class HistoryLoggingMixin:
    def perform_create(self, serializer):
        serializer.save()
        HistoricalVersion.save_version(serializer, "create")

    def perform_update(self, serializer):
        serializer.save()
        HistoricalVersion.save_version(serializer, "update")
