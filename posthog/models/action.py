import datetime
import json

import celery
from django.conf import settings
from django.core.exceptions import EmptyResultSet
from django.db import connection, models, transaction
from django.db.models import Q
from django.db.models.signals import post_delete, post_save
from django.dispatch.dispatcher import receiver
from django.utils import timezone
from rest_hooks.signals import raw_hook_event
from sentry_sdk import capture_exception

from posthog.redis import get_client


class Action(models.Model):
    class Meta:
        indexes = [
            models.Index(fields=["team_id", "-updated_at"]),
        ]

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

    def calculate_events(self, start=None, end=None):
        recalculate_all = False
        if start is None and end is None:
            recalculate_all = True
        if start is None:
            start = datetime.date(1990, 1, 1)
        if end is None:
            end = timezone.now() + datetime.timedelta(days=1)

        last_calculated_at = self.last_calculated_at
        now_calculated_at = timezone.now()
        self.is_calculating = True
        self.save()
        from .event import Event

        try:
            if recalculate_all:
                event_queryset = Event.objects.query_db_by_action(self).only("pk")
            else:
                event_queryset = Event.objects.query_db_by_action(self, start=start, end=end).only("pk")
            event_query, params = event_queryset.query.sql_with_params()
        except EmptyResultSet:
            self.events.all().delete()
        else:
            delete_query = f"""DELETE FROM "posthog_action_events" WHERE "action_id" = {self.pk}"""

            if not recalculate_all:
                delete_query += f""" AND "event_id" IN (
                    SELECT id FROM posthog_event
                    WHERE "created_at" >= '{start.isoformat()}' AND "created_at" < '{end.isoformat()}'
                )"""

            insert_query = """INSERT INTO "posthog_action_events" ("action_id", "event_id")
                            {}
                        ON CONFLICT DO NOTHING
                    """.format(
                event_query.replace("SELECT ", f"SELECT {self.pk}, ", 1)
            )

            cursor = connection.cursor()
            with transaction.atomic():
                try:
                    cursor.execute(delete_query + ";" + insert_query, params)
                except Exception as err:
                    capture_exception(err)
        finally:
            self.is_calculating = False
            self.last_calculated_at = now_calculated_at
            self.save()

    def on_perform(self, event):
        from posthog.api.event import EventSerializer
        from posthog.api.person import PersonSerializer

        event.action = self
        event.serialized_person = PersonSerializer(event.person).data
        payload = EventSerializer(event).data
        raw_hook_event.send(
            sender=None, event_name="action_performed", instance=self, payload=payload, user=event.team,
        )

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


@receiver(post_save, sender=Action)
def action_saved(sender, instance: Action, created, **kwargs):
    get_client().publish("reload-action", json.dumps({"teamId": instance.team_id, "actionId": instance.id}))


@receiver(post_delete, sender=Action)
def action_deleted(sender, instance: Action, **kwargs):
    get_client().publish("drop-action", json.dumps({"teamId": instance.team_id, "actionId": instance.id}))
