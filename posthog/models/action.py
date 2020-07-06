from django.db import models, connection, transaction
from django.core.exceptions import EmptyResultSet
from .user import User
from sentry_sdk import capture_exception


class Action(models.Model):
    class Meta:
        indexes = [
            models.Index(fields=["team_id", "-updated_at"]),
        ]

    def calculate_events(self):
        self.is_calculating = True
        self.save()
        from .event import Event

        try:
            event_query, params = Event.objects.query_db_by_action(self).only("pk").query.sql_with_params()
        except EmptyResultSet:
            self.is_calculating = False
            self.save()
            self.events.all().delete()
            return

        query = """
        DELETE FROM "posthog_action_events" WHERE "action_id" = {};
        INSERT INTO "posthog_action_events" ("action_id", "event_id")
        {}
        ON CONFLICT DO NOTHING
        """.format(
            self.pk, event_query.replace("SELECT ", "SELECT {}, ".format(self.pk), 1)
        )

        cursor = connection.cursor()
        with transaction.atomic():
            try:
                cursor.execute(query, params)
            except:
                capture_exception()

        self.is_calculating = False
        self.save()

    name: models.CharField = models.CharField(max_length=400, null=True, blank=True)
    team: models.ForeignKey = models.ForeignKey("Team", on_delete=models.CASCADE)
    created_at: models.DateTimeField = models.DateTimeField(auto_now_add=True, blank=True)
    created_by: models.ForeignKey = models.ForeignKey(User, on_delete=models.CASCADE, null=True, blank=True)
    deleted: models.BooleanField = models.BooleanField(default=False)
    events: models.ManyToManyField = models.ManyToManyField("Event", blank=True)
    post_to_slack: models.BooleanField = models.BooleanField(default=False)
    is_calculating: models.BooleanField = models.BooleanField(default=False)
    updated_at: models.DateTimeField = models.DateTimeField(auto_now=True)

    def __str__(self):
        return self.name
