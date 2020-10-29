import os
import time

import statsd  # type: ignore
from celery import Celery
from celery.schedules import crontab
from celery.signals import task_prerun, worker_process_init
from django.conf import settings
from django.db import connection
from django.utils import timezone

from posthog.cache import get_redis_instance

# set the default Django settings module for the 'celery' program.
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "posthog.settings")

app = Celery("posthog")

# Using a string here means the worker doesn't have to serialize
# the configuration object to child processes.
# - namespace='CELERY' means all celery-related configuration keys
#   should have a `CELERY_` prefix.
app.config_from_object("django.conf:settings", namespace="CELERY")

# Load task modules from all registered Django app configs.
app.autodiscover_tasks()

# Make sure Redis doesn't add too many connections
# https://stackoverflow.com/questions/47106592/redis-connections-not-being-released-after-celery-task-is-complete
app.conf.broker_pool_limit = 0

# How frequently do we want to calculate action -> event relationships if async is enabled
ACTION_EVENT_MAPPING_INTERVAL_MINUTES = 10

statsd.Connection.set_defaults(host=settings.STATSD_HOST, port=settings.STATSD_PORT)


@app.on_after_configure.connect
def setup_periodic_tasks(sender, **kwargs):
    if not settings.DEBUG:
        sender.add_periodic_task(1.0, redis_celery_queue_depth.s(), name="1 sec queue probe", priority=0)

    # Heartbeat every 10sec to make sure the worker is alive
    sender.add_periodic_task(10.0, redis_heartbeat.s(), name="10 sec heartbeat", priority=0)

    # update events table partitions twice a week
    sender.add_periodic_task(
        crontab(day_of_week="mon,fri"), update_event_partitions.s(),  # check twice a week
    )

    if getattr(settings, "MULTI_TENANCY", False) or os.environ.get("SESSION_RECORDING_RETENTION_CRONJOB", False):

        sender.add_periodic_task(crontab(minute=0, hour="*/12"), run_session_recording_retention.s())

    # send weekly status report on non-PostHog Cloud instances
    if not getattr(settings, "MULTI_TENANCY", False):
        sender.add_periodic_task(crontab(day_of_week="mon"), status_report.s())

    # send weekly email report (~ 8:00 SF / 16:00 UK / 17:00 EU)
    sender.add_periodic_task(crontab(day_of_week="mon", hour=15), send_weekly_email_report.s())

    sender.add_periodic_task(crontab(day_of_week="fri"), clean_stale_partials.s())

    sender.add_periodic_task(15 * 60, calculate_cohort.s(), name="debug")
    sender.add_periodic_task(600, check_cached_items.s(), name="check dashboard items")

    if settings.ASYNC_EVENT_ACTION_MAPPING:
        sender.add_periodic_task(
            (60 * ACTION_EVENT_MAPPING_INTERVAL_MINUTES),
            calculate_event_action_mappings.s(),
            name="calculate event action mappings",
            expires=(60 * ACTION_EVENT_MAPPING_INTERVAL_MINUTES),
        )


@app.task
def redis_heartbeat():
    get_redis_instance().set("POSTHOG_HEARTBEAT", int(time.time()))


@app.task
def redis_celery_queue_depth():
    try:
        g = statsd.Gauge("%s_posthog_celery" % (settings.STATSD_PREFIX,))
        llen = get_redis_instance().llen("celery")
        g.send("queue_depth", llen)
    except:
        # if we can't connect to statsd don't complain about it.
        # not every installation will have statsd available
        return


@app.task
def update_event_partitions():
    with connection.cursor() as cursor:
        cursor.execute(
            "DO $$ BEGIN IF (SELECT exists(select * from pg_proc where proname = 'update_partitions')) THEN PERFORM update_partitions(); END IF; END $$"
        )


@app.task
def clean_stale_partials():
    """Clean stale (meaning older than 7 days) partial social auth sessions."""
    from social_django.models import Partial

    Partial.objects.filter(timestamp__lt=timezone.now() - timezone.timedelta(7)).delete()


@app.task
def status_report():
    from posthog.tasks.status_report import status_report

    status_report()


@app.task
def run_session_recording_retention():
    from posthog.tasks.session_recording_retention import session_recording_retention_scheduler

    session_recording_retention_scheduler()


@app.task
def calculate_event_action_mappings():
    from posthog.tasks.calculate_action import calculate_actions_from_last_calculation

    calculate_actions_from_last_calculation()


@app.task
def calculate_cohort():
    from posthog.tasks.calculate_cohort import calculate_cohorts

    calculate_cohorts()


@app.task
def check_cached_items():
    from posthog.tasks.update_cache import update_cached_items

    update_cached_items()


@app.task(ignore_result=True)
def update_cache_item_task(key: str, cache_type: str, payload: dict) -> None:
    from posthog.tasks.update_cache import update_cache_item

    update_cache_item(key, cache_type, payload)


@app.task
def send_weekly_email_report():
    if settings.EMAIL_REPORTS_ENABLED:
        from posthog.tasks.email import send_weekly_email_reports

        send_weekly_email_reports()


@app.task(bind=True)
def debug_task(self):
    print("Request: {0!r}".format(self.request))
