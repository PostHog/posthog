import os
import time

import statsd
from celery import Celery
from celery.schedules import crontab
from django.conf import settings
from django.db import connection
from django.utils import timezone

from posthog.ee import is_ee_enabled
from posthog.redis import get_client

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

if settings.STATSD_HOST is not None:
    statsd.Connection.set_defaults(host=settings.STATSD_HOST, port=settings.STATSD_PORT)


@app.on_after_configure.connect
def setup_periodic_tasks(sender, **kwargs):
    if not settings.DEBUG:
        sender.add_periodic_task(1.0, redis_celery_queue_depth.s(), name="1 sec queue probe", priority=0)

    # Heartbeat every 10sec to make sure the worker is alive
    sender.add_periodic_task(10.0, redis_heartbeat.s(), name="10 sec heartbeat", priority=0)

    # update events table partitions twice a week
    sender.add_periodic_task(
        crontab(day_of_week="mon,fri", hour=0, minute=0), update_event_partitions.s(),  # check twice a week
    )

    if getattr(settings, "MULTI_TENANCY", False) and not is_ee_enabled():
        sender.add_periodic_task(crontab(minute=0, hour="*/12"), run_session_recording_retention.s())

    # send weekly status report on non-PostHog Cloud instances
    if not getattr(settings, "MULTI_TENANCY", False):
        sender.add_periodic_task(crontab(day_of_week="mon", hour=0, minute=0), status_report.s())

    # Cloud (posthog-production) cron jobs
    if getattr(settings, "MULTI_TENANCY", False):
        sender.add_periodic_task(crontab(hour=0, minute=0), calculate_billing_daily_usage.s())  # every day midnight UTC

    # send weekly email report (~ 8:00 SF / 16:00 UK / 17:00 EU)
    sender.add_periodic_task(crontab(day_of_week="mon", hour=15, minute=0), send_weekly_email_report.s())

    sender.add_periodic_task(crontab(day_of_week="fri", hour=0, minute=0), clean_stale_partials.s())

    sender.add_periodic_task(90, check_cached_items.s(), name="check dashboard items")

    if is_ee_enabled():
        sender.add_periodic_task(120, clickhouse_lag.s(), name="clickhouse table lag")
        sender.add_periodic_task(120, clickhouse_row_count.s(), name="clickhouse events table row count")
        sender.add_periodic_task(120, clickhouse_part_count.s(), name="clickhouse table parts count")

    sender.add_periodic_task(60, calculate_cohort.s(), name="recalculate cohorts")

    if settings.ASYNC_EVENT_ACTION_MAPPING:
        sender.add_periodic_task(
            (60 * ACTION_EVENT_MAPPING_INTERVAL_MINUTES),
            calculate_event_action_mappings.s(),
            name="calculate event action mappings",
            expires=(60 * ACTION_EVENT_MAPPING_INTERVAL_MINUTES),
        )


@app.task(ignore_result=True)
def redis_heartbeat():
    get_client().set("POSTHOG_HEARTBEAT", int(time.time()))


CLICKHOUSE_TABLES = [
    "events",
    "sharded_events",
    "person",
    "sharded_person",
    "person_distinct_id",
    "sharded_person_distinct_id",
    "session_recording_events",
    "sharded_session_recording_events",
]


@app.task(ignore_result=True)
def clickhouse_lag():
    if is_ee_enabled() and settings.EE_AVAILABLE:
        from ee.clickhouse.client import sync_execute

        for table in CLICKHOUSE_TABLES:
            try:
                QUERY = (
                    """select max(_timestamp) observed_ts, now() now_ts, now() - max(_timestamp) as lag from {table};"""
                )
                query = QUERY.format(table=table)
                lag = sync_execute(query)[0][2]
                g = statsd.Gauge("%s_posthog_celery" % (settings.STATSD_PREFIX,))
                g.send("clickhouse_{table}_table_lag_seconds".format(table=table), lag)
            except:
                pass
    else:
        pass


@app.task(ignore_result=True)
def clickhouse_row_count():
    if is_ee_enabled() and settings.EE_AVAILABLE:
        from ee.clickhouse.client import sync_execute

        for table in CLICKHOUSE_TABLES:
            try:
                QUERY = """select count(1) freq from {table};"""
                query = QUERY.format(table=table)
                rows = sync_execute(query)[0][0]
                g = statsd.Gauge("%s_posthog_celery" % (settings.STATSD_PREFIX,))
                g.send("clickhouse_{table}_table_row_count".format(table=table), rows)
            except:
                pass
    else:
        pass


@app.task(ignore_result=True)
def clickhouse_part_count():
    if is_ee_enabled() and settings.EE_AVAILABLE:
        from ee.clickhouse.client import sync_execute

        QUERY = """
            select table, count(1) freq
            from system.parts
            group by table
            order by freq desc; 
        """
        rows = sync_execute(QUERY)
        for (table, parts) in rows:
            g = statsd.Gauge("%s_posthog_celery" % (settings.STATSD_PREFIX,))
            g.send("clickhouse_{table}_table_parts_count".format(table=table), parts)
    else:
        pass


@app.task(ignore_result=True)
def redis_celery_queue_depth():
    try:
        g = statsd.Gauge("%s_posthog_celery" % (settings.STATSD_PREFIX,))
        llen = get_client().llen("celery")
        g.send("queue_depth", llen)
    except:
        # if we can't connect to statsd don't complain about it.
        # not every installation will have statsd available
        return


@app.task(ignore_result=True)
def update_event_partitions():
    with connection.cursor() as cursor:
        cursor.execute(
            "DO $$ BEGIN IF (SELECT exists(select * from pg_proc where proname = 'update_partitions')) THEN PERFORM update_partitions(); END IF; END $$"
        )


@app.task(ignore_result=True)
def clean_stale_partials():
    """Clean stale (meaning older than 7 days) partial social auth sessions."""
    from social_django.models import Partial

    Partial.objects.filter(timestamp__lt=timezone.now() - timezone.timedelta(7)).delete()


@app.task(ignore_result=True)
def status_report():
    from posthog.tasks.status_report import status_report

    status_report()


@app.task(ignore_result=True)
def run_session_recording_retention():
    from posthog.tasks.session_recording_retention import session_recording_retention_scheduler

    session_recording_retention_scheduler()


@app.task(ignore_result=True)
def calculate_event_action_mappings():
    from posthog.tasks.calculate_action import calculate_actions_from_last_calculation

    calculate_actions_from_last_calculation()


@app.task(ignore_result=True)
def calculate_cohort():
    from posthog.tasks.calculate_cohort import calculate_cohorts

    calculate_cohorts()


@app.task(ignore_result=True)
def check_cached_items():
    from posthog.tasks.update_cache import update_cached_items

    update_cached_items()


@app.task(ignore_result=True)
def update_cache_item_task(key: str, cache_type, payload: dict) -> None:
    from posthog.tasks.update_cache import update_cache_item

    update_cache_item(key, cache_type, payload)


@app.task(ignore_result=True)
def send_weekly_email_report():
    if settings.EMAIL_REPORTS_ENABLED:
        from posthog.tasks.email import send_weekly_email_reports

        send_weekly_email_reports()


@app.task(ignore_result=True, bind=True)
def debug_task(self):
    print("Request: {0!r}".format(self.request))


@app.task(ignore_result=True)
def calculate_event_property_usage():
    from posthog.tasks.calculate_event_property_usage import calculate_event_property_usage

    calculate_event_property_usage()


@app.task(ignore_result=True)
def calculate_billing_daily_usage():
    try:
        from multi_tenancy.tasks import compute_daily_usage_for_organizations  # noqa: F401
    except ImportError:
        pass
    else:
        compute_daily_usage_for_organizations()
