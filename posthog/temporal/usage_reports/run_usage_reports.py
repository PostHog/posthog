import json
import logging
import dataclasses
from datetime import timedelta
from typing import Optional

from django.conf import settings

import structlog
from asgiref.sync import sync_to_async
from dateutil import parser
from temporalio import activity, common, workflow

from posthog.exceptions_capture import capture_exception
from posthog.sync import database_sync_to_async
from posthog.tasks.usage_report import (
    OrgReport,
    _add_team_report_to_org_reports,
    _get_all_usage_data,
    _get_full_org_usage_report,
    _get_full_org_usage_report_as_dict,
    _get_team_report,
    _get_teams_for_usage_reports,
    _queue_report,
    capture_report,
    convert_team_usage_rows_to_dict,
    get_instance_metadata,
    get_ph_client,
    has_non_zero_usage,
)
from posthog.temporal.common.base import PostHogWorkflow
from posthog.temporal.common.heartbeat import Heartbeater
from posthog.utils import get_instance_region, get_previous_day

logger = structlog.get_logger()
logging.basicConfig(level=logging.INFO)


@dataclasses.dataclass
class RunUsageReportsInputs:
    at: Optional[str] = None
    skip_capture_event: Optional[bool] = False


@dataclasses.dataclass
class QueryUsageReportsInputs:
    at: Optional[str] = None
    skip_capture_event: Optional[bool] = False


@activity.defn(name="query-usage-reports")
async def query_usage_reports(
    inputs: QueryUsageReportsInputs,
) -> None:
    async with Heartbeater():
        import posthoganalytics

        are_usage_reports_disabled = posthoganalytics.feature_enabled(
            "disable-usage-reports", "internal_billing_events"
        )
        if are_usage_reports_disabled:
            capture_exception(Exception(f"Usage reports are disabled for {inputs.at}"))
            return None

        at_date = parser.parse(inputs.at) if inputs.at else None
        period = get_previous_day(at=at_date)
        period_start, period_end = period

        print(f"Querying all org reports {period_start} - {period_end}")  # noqa: T201

        @database_sync_to_async
        def async_get_all_usage_data(p_start, p_end):
            return _get_all_usage_data(p_start, p_end)

        def convert_to_team_rows(raw_data):
            result = {}
            for key, rows in raw_data.items():
                result[key] = convert_team_usage_rows_to_dict(rows)
            return result

        raw_data = await async_get_all_usage_data(period_start, period_end)

        all_data = convert_to_team_rows(raw_data)

        print("Querying all teams")  # noqa: T201

        @database_sync_to_async
        def async_get_teams_for_usage_reports():
            return _get_teams_for_usage_reports()

        teams = await async_get_teams_for_usage_reports()

        print(f"Querying all teams complete {len(teams)} teams")  # noqa: T201

        org_reports: dict[str, OrgReport] = {}

        print("Generating org reports")  # noqa: T201

        @database_sync_to_async
        def async_add_team_report_to_org_reports(o_r, t, t_r, p_start):
            return _add_team_report_to_org_reports(o_r, t, t_r, p_start)

        for team in teams:
            team_report = _get_team_report(all_data, team)
            await async_add_team_report_to_org_reports(org_reports, team, team_report, period_start)

        print(f"Generating org reports complete {len(org_reports)} orgs")  # noqa: T201

        @sync_to_async
        def async_get_instance_metadata(p):
            return get_instance_metadata(p)

        instance_metadata = await async_get_instance_metadata(period)

        producer = None
        try:
            if settings.EE_AVAILABLE:
                from ee.sqs.SQSProducer import get_sqs_producer

                producer = get_sqs_producer("usage_reports")
        except Exception:
            pass

        pha_client = get_ph_client(sync_mode=True)

        total_orgs = len(org_reports)
        total_orgs_sent = 0

        pha_client.capture(
            distinct_id="internal_billing_events",
            event="usage reports - starting to send",
            properties={
                "total_orgs": total_orgs,
                "period_start": period_start.isoformat(),
                "period_end": period_end.isoformat(),
                "region": get_instance_region(),
            },
            groups={"instance": settings.SITE_URL},
        )

        print(f"Sending usage reports {total_orgs} orgs")  # noqa: T201

        org_count = 0
        for org_report in org_reports.values():
            try:
                org_count += 1
                if org_count % 500 == 0:
                    print(f"Processed {org_count}/{total_orgs} organizations...")  # noqa: T201

                organization_id = org_report.organization_id

                full_report = _get_full_org_usage_report(org_report, instance_metadata)
                full_report_dict = _get_full_org_usage_report_as_dict(full_report)

                @sync_to_async
                def async_capture_report(oid, frd, ad) -> None:
                    try:
                        at_date_str = ad.isoformat() if ad else None
                        capture_report(
                            organization_id=oid,
                            full_report_dict=frd,
                            at_date=at_date_str,
                        )
                    except Exception as err:
                        logger.exception(f"Error capturing report for organization {oid}: {err}")

                # First capture the events to PostHog
                if not inputs.skip_capture_event:
                    await async_capture_report(organization_id, full_report_dict, at_date)

                @sync_to_async
                def async_queue_report(p, oid, frd) -> bool:
                    try:
                        _queue_report(p, oid, frd)
                        return True
                    except Exception as err:
                        logger.exception(f"Error queueing report for organization {oid}: {err}")
                        return False

                # Then send the reports to billing through SQS (only if the producer is available)
                if has_non_zero_usage(full_report) and producer:
                    success = await async_queue_report(producer, organization_id, full_report_dict)
                    if success:
                        total_orgs_sent += 1

            except Exception as loop_err:
                logger.exception(f"Error processing organization report: {loop_err}")

        print(f"Total orgs: {total_orgs}")  # noqa: T201
        print(f"Total orgs sent: {total_orgs_sent}")  # noqa: T201

        pha_client.capture(
            distinct_id="internal_billing_events",
            event="usage reports - sending complete",
            properties={
                "total_orgs": total_orgs,
                "total_orgs_sent": total_orgs_sent,
                "period_start": period_start.isoformat(),
                "period_end": period_end.isoformat(),
                "region": get_instance_region(),
            },
            groups={"instance": settings.SITE_URL},
        )
        pha_client.flush()  # Flush and close the client

        return None


@workflow.defn(name="run-usage-reports")
class RunUsageReportsWorkflow(PostHogWorkflow):
    @staticmethod
    def parse_inputs(inputs: list[str]) -> RunUsageReportsInputs:
        """Parse inputs from the management command CLI."""
        loaded = json.loads(inputs[0])
        return RunUsageReportsInputs(**loaded)

    @workflow.run
    async def run(self, inputs: RunUsageReportsInputs) -> None:
        try:
            query_usage_reports_inputs = QueryUsageReportsInputs(
                at=inputs.at,
                skip_capture_event=inputs.skip_capture_event,
            )
            await workflow.execute_activity(
                query_usage_reports,
                query_usage_reports_inputs,
                start_to_close_timeout=timedelta(minutes=40),
                retry_policy=common.RetryPolicy(
                    maximum_attempts=3,
                    initial_interval=timedelta(minutes=1),
                ),
                heartbeat_timeout=timedelta(minutes=4),
            )

        except Exception as e:
            logger.exception("Error running usage reports", error=e)
            capture_exception(e)
            raise
