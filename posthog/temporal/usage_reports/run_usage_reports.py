import json
from temporalio import activity, workflow, common
from datetime import timedelta
from typing import Optional
import dataclasses
import structlog
import logging

from dateutil import parser
from django.conf import settings
from posthog.temporal.common.base import PostHogWorkflow
from posthog.exceptions_capture import capture_exception
from posthog.temporal.common.heartbeat import Heartbeater
from asgiref.sync import sync_to_async

from posthog.utils import (
    get_instance_region,
    get_previous_day,
)

from posthog.tasks.usage_report import (
    get_instance_metadata,
    get_ph_client,
    _get_all_org_reports,
    _get_full_org_usage_report,
    _get_full_org_usage_report_as_dict,
    has_non_zero_usage,
    _queue_report,
    capture_report,
    OrgReport,
)

logger = structlog.get_logger()
logging.basicConfig(level=logging.INFO)


@dataclasses.dataclass
class RunUsageReportsInputs:
    at: Optional[str] = None
    skip_capture_event: Optional[bool] = False


@dataclasses.dataclass
class QueryUsageReportsInputs:
    at: Optional[str] = None


@dataclasses.dataclass
class QueryUsageReportsResult:
    org_reports: dict[str, OrgReport]


@dataclasses.dataclass
class SendUsageReportsInputs:
    org_reports: dict[str, OrgReport]
    skip_capture_event: Optional[bool] = False
    at: Optional[str] = None


@activity.defn(name="query-usage-reports")
async def query_usage_reports(
    inputs: QueryUsageReportsInputs,
) -> QueryUsageReportsResult:
    async with Heartbeater():
        import posthoganalytics
        from sentry_sdk import capture_message

        are_usage_reports_disabled = posthoganalytics.feature_enabled(
            "disable-usage-reports", "internal_billing_events"
        )
        if are_usage_reports_disabled:
            capture_message(f"Usage reports are disabled for {inputs.at}")
            return QueryUsageReportsResult(
                org_reports={},
            )

        at_date = parser.parse(inputs.at) if inputs.at else None
        period = get_previous_day(at=at_date)
        period_start, period_end = period

        @sync_to_async
        def get_all_org_reports(ps, pe):
            return _get_all_org_reports(ps, pe)

        org_reports = await get_all_org_reports(period_start, period_end)

        return QueryUsageReportsResult(
            org_reports=org_reports,
        )


@activity.defn(name="send-usage-reports")
async def send_usage_reports(
    inputs: SendUsageReportsInputs,
) -> None:
    async with Heartbeater():
        at_date = parser.parse(inputs.at) if inputs.at else None
        period = get_previous_day(at=at_date)
        period_start, period_end = period

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

        total_orgs = len(inputs.org_reports)
        total_orgs_sent = 0

        pha_client.capture(
            "internal_billing_events",
            "usage reports - starting to send",
            {
                "total_orgs": total_orgs,
                "period_start": period_start.isoformat(),
                "period_end": period_end.isoformat(),
                "region": get_instance_region(),
            },
            groups={"instance": settings.SITE_URL},
        )

        for org_report in inputs.org_reports.values():
            try:
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

        pha_client.capture(
            "internal_billing_events",
            "usage reports - sending complete",
            {
                "total_orgs": total_orgs,
                "total_orgs_sent": total_orgs_sent,
                "period_start": period_start.isoformat(),
                "period_end": period_end.isoformat(),
                "region": get_instance_region(),
            },
            groups={"instance": settings.SITE_URL},
        )
        pha_client.flush()  # Flush and close the client


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
            )
            query_usage_reports_result = await workflow.execute_activity(
                query_usage_reports,
                query_usage_reports_inputs,
                start_to_close_timeout=timedelta(minutes=20),
                retry_policy=common.RetryPolicy(
                    maximum_attempts=3,
                    initial_interval=timedelta(minutes=1),
                ),
                heartbeat_timeout=timedelta(seconds=30),
            )

            if not query_usage_reports_result.org_reports:
                return

            send_usage_reports_inputs = SendUsageReportsInputs(
                org_reports=query_usage_reports_result.org_reports,
                skip_capture_event=inputs.skip_capture_event,
                at=inputs.at,
            )
            await workflow.execute_activity(
                send_usage_reports,
                send_usage_reports_inputs,
                start_to_close_timeout=timedelta(minutes=30),
                retry_policy=common.RetryPolicy(
                    maximum_attempts=3,
                    initial_interval=timedelta(minutes=1),
                ),
                heartbeat_timeout=timedelta(seconds=30),
            )

        except Exception as e:
            capture_exception(e)
            raise
