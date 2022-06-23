from random import randrange

from celery import Celery, current_app
from celery.schedules import crontab
from django.conf import settings

from posthog.utils import get_crontab

app = current_app._get_current_object()


@app.on_after_configure.connect
def setup_periodic_tasks(sender: Celery, **kwargs):
    sender.add_periodic_task(
        crontab(
            hour=0, minute=randrange(0, 40)
        ),  # every day at a random minute past midnight. Sends data from the preceding whole day.
        send_org_usage_report.s(),
        name="send event usage report",
    )

    sender.add_periodic_task(
        crontab(hour=0, minute=randrange(0, 40)), clickhouse_send_license_usage.s()
    )  # every day at a random minute past midnight. Randomize to avoid overloading license.posthog.com

    materialize_columns_crontab = get_crontab(settings.MATERIALIZE_COLUMNS_SCHEDULE_CRON)

    if materialize_columns_crontab:
        sender.add_periodic_task(
            materialize_columns_crontab, clickhouse_materialize_columns.s(), name="clickhouse materialize columns",
        )

        sender.add_periodic_task(
            crontab(hour="*/4", minute=0),
            clickhouse_mark_all_materialized.s(),
            name="clickhouse mark all columns as materialized",
        )

    # Hourly check for email subscriptions
    sender.add_periodic_task(crontab(hour="*", minute=55), schedule_all_subscriptions.s())


def recompute_materialized_columns_enabled() -> bool:
    from posthog.models.instance_setting import get_instance_setting

    if get_instance_setting("MATERIALIZED_COLUMNS_ENABLED") and get_instance_setting(
        "COMPUTE_MATERIALIZED_COLUMNS_ENABLED"
    ):
        return True
    return False


@app.task(ignore_result=True)
def clickhouse_materialize_columns():
    if recompute_materialized_columns_enabled():
        from ee.clickhouse.materialized_columns.analyze import materialize_properties_task

        materialize_properties_task()


@app.task(ignore_result=True)
def clickhouse_mark_all_materialized():
    if recompute_materialized_columns_enabled():
        from ee.tasks.materialized_columns import mark_all_materialized

        mark_all_materialized()


@app.task(ignore_result=True)
def clickhouse_send_license_usage():
    if not settings.MULTI_TENANCY:
        from ee.tasks.send_license_usage import send_license_usage

        send_license_usage()


@app.task(ignore_result=True)
def send_org_usage_report():
    from ee.tasks.org_usage_report import send_all_org_usage_reports

    send_all_org_usage_reports()


@app.task(ignore_result=True)
def schedule_all_subscriptions():
    from ee.tasks.subscriptions import schedule_all_subscriptions as _schedule_all_subscriptions

    _schedule_all_subscriptions()
