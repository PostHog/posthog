import datetime

from django.core.exceptions import EmptyResultSet
from django.db import connection, models, transaction
from django.db.models import Q
from django.utils import timezone
from rest_hooks.signals import raw_hook_event
from sentry_sdk import capture_exception


class Action(models.Model):
    class Meta:
        indexes = [
            models.Index(fields=["team_id", "-updated_at"]),
        ]

    def calculate_events(self, start=None, end=None):
        recalculate_all = False
        if start is None and end is None:
            recalculate_all = True
        if start is None:
            start = datetime.date(1990, 1, 1)
        if end is None:
            end = timezone.now() + datetime.timedelta(days=1)

        calculated_at = timezone.now()
        self.is_calculating = True
        self.save()
        from .event import Event

        try:
            if recalculate_all:
                event_query, params = Event.objects.query_db_by_action(self).only("pk").query.sql_with_params()
            else:
                event_query, params = (
                    Event.objects.query_db_by_action(self, start=start, end=end).only("pk").query.sql_with_params()
                )

        except EmptyResultSet:
            self.last_calculated_at = calculated_at
            self.is_calculating = False
            self.save()
            self.events.all().delete()
            return

        query = """DELETE FROM "posthog_action_events" WHERE "action_id" = {}""".format(self.pk)

        period_delete_query = """AND "event_id" in
                       (SELECT id
                        FROM posthog_event
                        WHERE "created_at" >= '{}'
                        AND "created_at" < '{}');
                """.format(
            start.isoformat(), end.isoformat()
        )

        insert_query = """INSERT INTO "posthog_action_events" ("action_id", "event_id")
                        {}
                    ON CONFLICT DO NOTHING
                 """.format(
            event_query.replace("SELECT ", "SELECT {}, ".format(self.pk), 1)
        )

        if not recalculate_all:
            query += period_delete_query
        else:
            query += ";"

        query += insert_query

        cursor = connection.cursor()
        with transaction.atomic():
            try:
                cursor.execute(query, params)
            except Exception:
                capture_exception()

        self.is_calculating = False
        self.last_calculated_at = calculated_at
        self.save()

    def on_perform(self, event):
        from posthog.api.event import EventSerializer

        event.action = self
        raw_hook_event.send(
            sender=None,
            event_name="action_performed",
            instance=self,
            payload=EventSerializer(event).data,
            user=event.team,
        )

    name: models.CharField = models.CharField(max_length=400, null=True, blank=True)
    team: models.ForeignKey = models.ForeignKey("Team", on_delete=models.CASCADE)
    created_at: models.DateTimeField = models.DateTimeField(auto_now_add=True, blank=True)
    created_by: models.ForeignKey = models.ForeignKey("User", on_delete=models.CASCADE, null=True, blank=True)
    deleted: models.BooleanField = models.BooleanField(default=False)
    events: models.ManyToManyField = models.ManyToManyField("Event", blank=True)
    post_to_slack: models.BooleanField = models.BooleanField(default=False)
    slack_message_format: models.CharField = models.CharField(default="", max_length=200, blank=True)
    is_calculating: models.BooleanField = models.BooleanField(default=False)
    updated_at: models.DateTimeField = models.DateTimeField(auto_now=True)
    last_calculated_at: models.DateTimeField = models.DateTimeField(default=timezone.now, blank=True)

    def __str__(self):
        return self.name

    def get_analytics_metadata(self):
        return {
            "post_to_slack": self.post_to_slack,
            "name_length": len(self.name),
            "custom_slack_message_format": self.slack_message_format != "",
            "event_count_precalc": self.events.count(),  # `precalc` because events are computed async
            "step_count": self.steps.count(),
            "match_text_count": self.steps.exclude(Q(text="") | Q(text__isnull=True)).count(),
            "match_href_count": self.steps.exclude(Q(href="") | Q(href__isnull=True)).count(),
            "match_selector_count": self.steps.exclude(Q(selector="") | Q(selector__isnull=True)).count(),
            "match_url_count": self.steps.exclude(Q(url="") | Q(url__isnull=True)).count(),
            "has_properties": self.steps.exclude(properties=[]).exists(),
            "deleted": self.deleted,
        }
