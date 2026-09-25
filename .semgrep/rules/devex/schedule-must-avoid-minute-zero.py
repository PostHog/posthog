# Test cases for schedule-must-avoid-minute-zero.
# ruff: noqa
import datetime as dt
from datetime import timedelta

import dagster
from celery.schedules import crontab
from temporalio.client import ScheduleIntervalSpec, ScheduleSpec

from posthog.scheduling.jitter import deterministic_offset

# ruleid: schedule-must-avoid-minute-zero
sender.add_periodic_task(crontab(hour="*", minute="0"), refresh_cache.s())

# ruleid: schedule-must-avoid-minute-zero
sender.add_periodic_task(crontab(minute="0"), kill_stale_runs.s())

# ruleid: schedule-must-avoid-minute-zero
sender.add_periodic_task(crontab(minute="0", hour="*/12"), refresh_fields.s())

# ruleid: schedule-must-avoid-minute-zero
sender.add_periodic_task(crontab(minute=0), sweep.s())

# ok: schedule-must-avoid-minute-zero
sender.add_periodic_task(crontab(hour="*", minute="23"), refresh_cache.s())

# ok: schedule-must-avoid-minute-zero
sender.add_periodic_task(crontab(hour="3", minute="0"), daily_cleanup.s())

# ok: schedule-must-avoid-minute-zero
sender.add_periodic_task(crontab(minute="*/5"), poll.s())


# ruleid: schedule-must-avoid-minute-zero
@dagster.schedule(cron_schedule="0 * * * *", job=hourly_job)
def hourly_schedule(context):
    return dagster.RunRequest()


# ruleid: schedule-must-avoid-minute-zero
every_six_hours = dagster.ScheduleDefinition(job=job, cron_schedule="0 */6 * * *")


# ok: schedule-must-avoid-minute-zero
@dagster.schedule(cron_schedule="17 * * * *", job=hourly_job)
def offset_schedule(context):
    return dagster.RunRequest()


# ok: schedule-must-avoid-minute-zero
daily = dagster.ScheduleDefinition(job=job, cron_schedule="0 3 * * *")

# ruleid: schedule-must-avoid-minute-zero
hourly_cron = ScheduleSpec(cron_expressions=["0 * * * *"])

# ok: schedule-must-avoid-minute-zero
every_minute = ScheduleSpec(cron_expressions=["*/1 * * * *"])

# ok: schedule-must-avoid-minute-zero
daily_cron = ScheduleSpec(cron_expressions=["2 3 * * *"], jitter=timedelta(minutes=30))

# ruleid: schedule-must-avoid-minute-zero
hourly_interval = ScheduleIntervalSpec(every=timedelta(hours=1))

# ruleid: schedule-must-avoid-minute-zero
quarter_hour = ScheduleIntervalSpec(every=dt.timedelta(minutes=15))

# ruleid: schedule-must-avoid-minute-zero
named_interval = ScheduleIntervalSpec(every=SCHEDULE_INTERVAL)

# ok: schedule-must-avoid-minute-zero
offset_interval = ScheduleIntervalSpec(every=timedelta(hours=1), offset=timedelta(minutes=2))

# ok: schedule-must-avoid-minute-zero
entity_interval = ScheduleIntervalSpec(every=SCHEDULE_INTERVAL, offset=deterministic_offset(key, SCHEDULE_INTERVAL))

# ok: schedule-must-avoid-minute-zero
daily_interval = ScheduleIntervalSpec(every=timedelta(days=1))

# ruleid: schedule-must-avoid-minute-zero
six_hourly_interval = ScheduleIntervalSpec(every=timedelta(hours=6))

# ok: schedule-must-avoid-minute-zero
day_in_hours_interval = ScheduleIntervalSpec(every=timedelta(hours=24))
