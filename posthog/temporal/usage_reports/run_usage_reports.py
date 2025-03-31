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
from posthog.warehouse.util import database_sync_to_async
from posthog.utils import (
    get_instance_region,
    get_previous_day,
)

from posthog.tasks.usage_report import (
    get_instance_metadata,
    get_ph_client,
    _get_all_usage_data,
    convert_team_usage_rows_to_dict,
    _get_teams_for_usage_reports,
    _get_team_report,
    _get_full_org_usage_report,
    _get_full_org_usage_report_as_dict,
    has_non_zero_usage,
    get_org_user_count,
    _queue_report,
    capture_report,
    OrgReport,
    UsageReportCounters,
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
    skip_capture_event: Optional[bool] = False


@activity.defn(name="query-usage-reports")
async def query_usage_reports(
    inputs: QueryUsageReportsInputs,
) -> None:
    async with Heartbeater():
        import posthoganalytics
        from sentry_sdk import capture_message

        # Async functions
        @database_sync_to_async
        def async_get_all_usage_data(p_start, p_end):
            return _get_all_usage_data(p_start, p_end)

        @database_sync_to_async
        def async_get_teams_for_usage_reports():
            return _get_teams_for_usage_reports()

        @database_sync_to_async
        def async_get_team_report(a_data, t):
            return _get_team_report(a_data, t)

        @database_sync_to_async
        def async_get_instance_metadata(p):
            return get_instance_metadata(p)

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

        @sync_to_async
        def async_queue_report(p, oid, frd) -> bool:
            try:
                _queue_report(p, oid, frd)
                return True
            except Exception as err:
                logger.exception(f"Error queueing report for organization {oid}: {err}")
                return False

        @database_sync_to_async
        def async_get_org_user_count(oid):
            return get_org_user_count(oid)

        # Helpers
        def convert_to_team_rows(raw_data):
            result = {}
            for key, rows in raw_data.items():
                result[key] = convert_team_usage_rows_to_dict(rows)
            return result

        # Workflow
        are_usage_reports_disabled = posthoganalytics.feature_enabled(
            "disable-usage-reports", "internal_billing_events"
        )
        if are_usage_reports_disabled:
            capture_message(f"Usage reports are disabled for {inputs.at}")
            return None

        at_date = parser.parse(inputs.at) if inputs.at else None
        period = get_previous_day(at=at_date)
        period_start, period_end = period

        print(f"Querying all org reports {period_start} - {period_end}")  # noqa: T201

        raw_data = await async_get_all_usage_data(period_start, period_end)
        all_data = convert_to_team_rows(raw_data)

        print("Querying all teams")  # noqa: T201

        teams = await async_get_teams_for_usage_reports()

        print(f"Querying all teams complete {len(teams)} teams")  # noqa: T201

        instance_metadata = await async_get_instance_metadata(period)

        producer = None
        try:
            if settings.EE_AVAILABLE:
                from ee.sqs.SQSProducer import get_sqs_producer

                producer = get_sqs_producer("usage_reports")
        except Exception:
            pass

        pha_client = get_ph_client(sync_mode=True)

        # Process teams by organization
        current_org_id = None
        current_org_report = None
        total_orgs = 0
        total_orgs_sent = 0
        org_count = 0

        print("Processing teams by organization")  # noqa: T201

        for team in teams:
            org_id = str(team.organization.id)

            # If we've moved to a new organization, process the previous one
            if current_org_id is not None and current_org_id != org_id:
                org_count += 1
                if org_count % 500 == 0:
                    print(f"Processed {org_count} organizations...")  # noqa: T201

                # Process the completed organization report
                try:
                    full_report = _get_full_org_usage_report(current_org_report, instance_metadata)
                    full_report_dict = _get_full_org_usage_report_as_dict(full_report)

                    # First capture the events to PostHog
                    if not inputs.skip_capture_event:
                        await async_capture_report(current_org_id, full_report_dict, at_date)

                    # Then send the reports to billing through SQS (only if the producer is available)
                    if has_non_zero_usage(full_report) and producer:
                        success = await async_queue_report(producer, current_org_id, full_report_dict)
                        if success:
                            total_orgs_sent += 1

                except Exception as loop_err:
                    logger.exception(f"Error processing organization report: {loop_err}")

                # Reset for the new organization
                current_org_report = None

            # Start a new organization or continue with the current one
            if current_org_report is None:
                total_orgs += 1
                current_org_id = org_id

                # Create a new org report
                team_report = await async_get_team_report(all_data, team)

                current_org_report = OrgReport(
                    date=period_start.strftime("%Y-%m-%d"),
                    organization_id=org_id,
                    organization_name=team.organization.name,
                    organization_created_at=team.organization.created_at.isoformat(),
                    organization_user_count=await async_get_org_user_count(org_id),
                    team_count=1,
                    teams={str(team.id): team_report},
                    **dataclasses.asdict(team_report),  # Clone the team report as the basis
                )
            else:
                # Add this team to the current org report
                team_report = await async_get_team_report(all_data, team)

                # Safety check to ensure team belongs to the current organization (should never happen)
                if str(team.organization.id) != current_org_id:
                    capture_message(f"Usage report: team organization mismatch: {team.id} {current_org_id}")
                    continue

                current_org_report.teams[str(team.id)] = team_report
                current_org_report.team_count += 1

                # Update the counters in the org report
                for field in dataclasses.fields(UsageReportCounters):
                    if hasattr(team_report, field.name):
                        setattr(
                            current_org_report,
                            field.name,
                            getattr(current_org_report, field.name) + getattr(team_report, field.name),
                        )

        # Process the last organization
        if current_org_report is not None:
            org_count += 1
            try:
                full_report = _get_full_org_usage_report(current_org_report, instance_metadata)
                full_report_dict = _get_full_org_usage_report_as_dict(full_report)

                # First capture the events to PostHog
                if not inputs.skip_capture_event:
                    await async_capture_report(current_org_id, full_report_dict, at_date)

                # Then send the reports to billing through SQS (only if the producer is available)
                if has_non_zero_usage(full_report) and producer:
                    success = await async_queue_report(producer, current_org_id, full_report_dict)
                    if success:
                        total_orgs_sent += 1

            except Exception as loop_err:
                logger.exception(f"Error processing organization report: {loop_err}")

        print(f"Total orgs before: {total_orgs}")  # noqa: T201
        print(f"Total orgs counted: {org_count}")  # noqa: T201
        print(f"Total orgs sent: {total_orgs_sent}")  # noqa: T201

        if get_instance_region():
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
