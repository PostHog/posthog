import asyncio
from collections.abc import Callable
from datetime import datetime, timedelta

import temporalio.workflow
from temporalio.common import RetryPolicy
from temporalio.exceptions import ActivityError, ApplicationError

from posthog.temporal.common.base import PostHogWorkflow

with temporalio.workflow.unsafe.imports_passed_through():
    from posthog.temporal.experiments.activities import (
        backfill_experiment_metric,
        calculate_experiment_regular_metric,
        calculate_experiment_saved_metric,
        create_recalculation_from_timeseries,
        get_experiment_regular_metrics_for_hour,
        get_experiment_regular_metrics_page,
        get_experiment_saved_metrics_for_hour,
        get_experiment_saved_metrics_page,
    )
    from posthog.temporal.experiments.models import (
        TIMESERIES_METRIC_MAX_ATTEMPTS,
        ExperimentRegularMetricsWorkflowInputs,
        ExperimentSavedMetricsWorkflowInputs,
        ExperimentTimeseriesRecalculationWorkflowInputs,
        HourlyRunContinuation,
        HourlyRunTotals,
        MetricsPageInput,
    )

MAX_CONCURRENT_METRICS = 10

# Experiments per discovery page. A page costs roughly (metrics + 1 publish) * 6 history events per
# experiment, so a page is a small fraction of the history budget between continue-as-new checks.
METRICS_PAGE_SIZE = 100

# Temporal Cloud terminates a workflow at 51,200 history events, silently from the workflow's point of
# view. Legs normally rotate on the server's own continue-as-new suggestion; this ceiling forces the
# rotation even if that suggestion never fires, with room for one more page plus retry noise below the cap.
FORCE_CONTINUE_HISTORY_EVENTS = 20_000


def _record_publish_outcome(succeeded: int, recalculations_synced: int) -> None:
    """Per-run counter behind the missing-publish alert: a run that computed metrics but published zero
    recalculation rows is the silent-failure mode where results exist yet never reach users.

    A single "missing" run can be legitimate (every row already covered by another run or a manual
    recalculation), so the threshold lives in the Grafana alert rule, not here. `workflow.metric_meter()`
    skips emission during replay, so no patch gate is needed."""
    if succeeded == 0:
        return
    status = "published" if recalculations_synced > 0 else "missing"
    try:
        temporalio.workflow.metric_meter().with_additional_attributes(
            {"workflow_type": temporalio.workflow.info().workflow_type, "status": status}
        ).create_counter(
            "experiment_timeseries_publish_runs",
            "Hourly experiment timeseries runs that computed metrics, by whether they published recalculation rows.",
        ).add(1)
    except Exception:
        # A meter failure must not fail a run whose calculations and publishes already finished.
        temporalio.workflow.logger.warning("Failed to record the publish outcome counter", exc_info=True)


async def _create_recalculations_from_timeseries(
    experiments: set[tuple[int, int]], run_started_at: datetime, semaphore: asyncio.Semaphore
) -> int:
    """One activity per (experiment, team) this run touched; returns how many recalculation rows gained copies.

    Pre-patch publish pass, kept only so executions recorded before the per-experiment publish replay
    deterministically."""

    async def _sync_experiment(experiment_id: int, team_id: int) -> str | None:
        async with semaphore:
            return await temporalio.workflow.execute_activity(
                create_recalculation_from_timeseries,
                args=[experiment_id, team_id, run_started_at.isoformat()],
                start_to_close_timeout=timedelta(minutes=5),
                retry_policy=RetryPolicy(maximum_attempts=3),
            )

    results = await asyncio.gather(
        *[_sync_experiment(experiment_id, team_id) for experiment_id, team_id in sorted(experiments)],
        return_exceptions=True,
    )
    return sum(1 for result in results if isinstance(result, str))


async def _calculate_and_publish_per_experiment(
    calculate_activity,
    experiment_metrics,
    run_started_at: datetime,
    semaphore: asyncio.Semaphore,
) -> tuple[list, int]:
    """Calculate each experiment's metrics and publish its recalculation as soon as its own metrics finish.

    Grouped per experiment so a slow experiment, or a worker restart mid-hour, delays only its own publish
    instead of every experiment in the batch. Metric activities share the caller's semaphore, so query
    concurrency is the same as one flat fan-out. Returns the per-metric results and the publish count.
    """

    async def _run_metric(em):
        async with semaphore:
            return await temporalio.workflow.execute_activity(
                calculate_activity,
                args=[em.experiment_id, em.metric_uuid, em.fingerprint],
                start_to_close_timeout=timedelta(minutes=15),
                retry_policy=RetryPolicy(
                    maximum_attempts=TIMESERIES_METRIC_MAX_ATTEMPTS,
                    initial_interval=timedelta(seconds=10),
                    maximum_interval=timedelta(seconds=60),
                ),
            )

    groups: dict[tuple[int, int | None], list] = {}
    for em in experiment_metrics:
        groups.setdefault((em.experiment_id, em.team_id), []).append(em)

    # Publishes get their own limit. Every metric task in the hour enqueues on the shared semaphore up
    # front and waiters are served in order, so a publish waiting in that queue would sit behind the whole
    # remaining batch, which recreates the end-of-hour barrier this function exists to remove.
    publish_semaphore = asyncio.Semaphore(MAX_CONCURRENT_METRICS)

    async def _run_experiment(experiment_id: int, team_id: int | None, metrics: list) -> tuple[list, bool]:
        metric_results = await asyncio.gather(*[_run_metric(em) for em in metrics], return_exceptions=True)
        if team_id is None:
            return metric_results, False
        try:
            async with publish_semaphore:
                synced = await temporalio.workflow.execute_activity(
                    create_recalculation_from_timeseries,
                    args=[experiment_id, team_id, run_started_at.isoformat()],
                    start_to_close_timeout=timedelta(minutes=5),
                    retry_policy=RetryPolicy(maximum_attempts=3),
                )
        except ActivityError:
            # A failed publish loses one experiment's freshness until the next run; it must not fail
            # the rest of the hour's calculations.
            return metric_results, False
        return metric_results, isinstance(synced, str)

    group_results = await asyncio.gather(
        *[_run_experiment(experiment_id, team_id, metrics) for (experiment_id, team_id), metrics in groups.items()]
    )
    results = [result for metric_results, _ in group_results for result in metric_results]
    published = sum(1 for _, synced in group_results if synced)
    return results, published


async def _run_hourly_chunked(
    discover_page_activity: Callable,
    calculate_activity: Callable,
    inputs: ExperimentRegularMetricsWorkflowInputs | ExperimentSavedMetricsWorkflowInputs,
    make_continuation_inputs: Callable[[HourlyRunContinuation], object],
) -> dict:
    """Process the hour's experiments in discovery pages and continue-as-new between pages.

    One execution per hour cannot hold the whole batch: at roughly 6 history events per activity the
    event cap allows ~8,500 activities, and the batch needs more, so Temporal Cloud terminated the run
    mid-batch and the experiments past the cutoff were silently skipped every day. Rotating legs keeps
    every leg's history bounded regardless of batch size.

    The cursor and totals travel in the continuation inputs, not in history, so each leg starts from an
    empty event log. The publish-outcome counter is emitted once, by the final leg, with chain totals.
    """
    continuation = inputs.continuation
    run_started_at = datetime.fromisoformat(continuation.run_started_at) if continuation else temporalio.workflow.now()
    totals = continuation.totals if continuation else HourlyRunTotals()
    cursor = continuation.after_experiment_id if continuation else 0
    semaphore = asyncio.Semaphore(MAX_CONCURRENT_METRICS)

    while True:
        page = await temporalio.workflow.execute_activity(
            discover_page_activity,
            MetricsPageInput(hour=inputs.hour, after_experiment_id=cursor, page_size=METRICS_PAGE_SIZE),
            start_to_close_timeout=timedelta(minutes=5),
            retry_policy=RetryPolicy(maximum_attempts=3),
        )

        # A page can be empty while more pages remain, when every scanned experiment's metrics were
        # filtered out. Loop termination is the cursor, never the metric count.
        if page.metrics:
            results, published = await _calculate_and_publish_per_experiment(
                calculate_activity, page.metrics, run_started_at, semaphore
            )
            totals.total += len(page.metrics)
            totals.published += published
            for result in results:
                if isinstance(result, BaseException) or not result.success:
                    totals.failed += 1
                else:
                    totals.succeeded += 1

        if page.next_after_experiment_id is None:
            break
        if page.next_after_experiment_id <= cursor:
            # A non-advancing cursor would re-process the same page forever. Fail the execution
            # visibly instead of retrying the workflow task into a wedge.
            raise ApplicationError(
                f"discovery cursor did not advance past {cursor}",
                non_retryable=True,
            )
        cursor = page.next_after_experiment_id

        info = temporalio.workflow.info()
        if info.is_continue_as_new_suggested() or info.get_current_history_length() > FORCE_CONTINUE_HISTORY_EVENTS:
            temporalio.workflow.logger.info(
                "Hourly experiment metrics run continuing as new",
                extra={"hour": inputs.hour, "after_experiment_id": cursor, "metrics_so_far": totals.total},
            )
            temporalio.workflow.continue_as_new(
                make_continuation_inputs(
                    HourlyRunContinuation(
                        after_experiment_id=cursor,
                        run_started_at=run_started_at.isoformat(),
                        totals=totals,
                    )
                )
            )

    _record_publish_outcome(totals.succeeded, totals.published)

    return {
        "hour": inputs.hour,
        "total": totals.total,
        "succeeded": totals.succeeded,
        "failed": totals.failed,
        "recalculations_synced": totals.published,
    }


@temporalio.workflow.defn(name="experiment-regular-metrics-workflow")
class ExperimentRegularMetricsWorkflow(PostHogWorkflow):
    """
    Workflow that calculates all experiment metrics for teams scheduled at a given hour.

    Runs daily per hour (24 schedules total). Each run pages through the hour's experiments by id and,
    per experiment, calculates its metrics in parallel (one activity per metric, shared concurrency
    limit), then assembles its completed metrics recalculation from this run's points. Between pages
    the run continues-as-new so no single execution's history approaches the Temporal event cap, which
    used to terminate the big hours mid-batch. The final leg returns the chain-wide summary.
    """

    @staticmethod
    def parse_inputs(inputs: list[str]) -> ExperimentRegularMetricsWorkflowInputs:
        return ExperimentRegularMetricsWorkflowInputs(hour=int(inputs[0]))

    @temporalio.workflow.run
    async def run(self, inputs: ExperimentRegularMetricsWorkflowInputs) -> dict:
        if temporalio.workflow.patched("experiment-hourly-chunked-2026-10"):
            return await _run_hourly_chunked(
                get_experiment_regular_metrics_page,
                calculate_experiment_regular_metric,
                inputs,
                lambda continuation: ExperimentRegularMetricsWorkflowInputs(
                    hour=inputs.hour, continuation=continuation
                ),
            )

        # Everything below is replay-only for executions recorded before the chunked path shipped.
        run_started_at = temporalio.workflow.now()

        # Step 1: Discover experiment-metrics for this hour
        experiment_metrics = await temporalio.workflow.execute_activity(
            get_experiment_regular_metrics_for_hour,
            inputs.hour,
            start_to_close_timeout=timedelta(minutes=5),
            retry_policy=RetryPolicy(maximum_attempts=3),
        )

        if not experiment_metrics:
            return {
                "hour": inputs.hour,
                "total": 0,
                "succeeded": 0,
                "failed": 0,
                "recalculations_synced": 0,
            }

        # Step 2: Per experiment, calculate its metrics and publish its recalculation as soon as they
        # finish, so a team's results land minutes after its own experiments compute instead of hours
        # after the whole batch. The patch gates keep replay of older histories deterministic.
        semaphore = asyncio.Semaphore(MAX_CONCURRENT_METRICS)

        if temporalio.workflow.patched("experiment-per-experiment-publish-2026-09"):
            results, recalculations_synced = await _calculate_and_publish_per_experiment(
                calculate_experiment_regular_metric, experiment_metrics, run_started_at, semaphore
            )
        else:

            async def _run_metric(em):
                async with semaphore:
                    return await temporalio.workflow.execute_activity(
                        calculate_experiment_regular_metric,
                        args=[em.experiment_id, em.metric_uuid, em.fingerprint],
                        start_to_close_timeout=timedelta(minutes=15),
                        retry_policy=RetryPolicy(
                            maximum_attempts=TIMESERIES_METRIC_MAX_ATTEMPTS,
                            initial_interval=timedelta(seconds=10),
                            maximum_interval=timedelta(seconds=60),
                        ),
                    )

            tasks = [_run_metric(em) for em in experiment_metrics]
            results = await asyncio.gather(*tasks, return_exceptions=True)

            recalculations_synced = 0
            if temporalio.workflow.patched("experiment-timeseries-recalculation-sync-2026-09"):
                recalculations_synced = await _create_recalculations_from_timeseries(
                    {(em.experiment_id, em.team_id) for em in experiment_metrics if em.team_id is not None},
                    run_started_at,
                    semaphore,
                )

        # Step 3: Summarize
        succeeded = 0
        failed = 0

        for result in results:
            if isinstance(result, BaseException):
                failed += 1
            elif result.success:
                succeeded += 1
            else:
                failed += 1

        _record_publish_outcome(succeeded, recalculations_synced)

        return {
            "hour": inputs.hour,
            "total": len(experiment_metrics),
            "succeeded": succeeded,
            "failed": failed,
            "recalculations_synced": recalculations_synced,
        }


@temporalio.workflow.defn(name="experiment-saved-metrics-workflow")
class ExperimentSavedMetricsWorkflow(PostHogWorkflow):
    """
    Workflow that calculates all experiment saved metrics for teams scheduled at a given hour.

    Runs daily per hour (24 schedules total). Same chunked shape as ExperimentRegularMetricsWorkflow:
    pages through the hour's experiments by id, calculates and publishes per experiment, and
    continues-as-new between pages to keep every execution's history bounded.
    """

    @staticmethod
    def parse_inputs(inputs: list[str]) -> ExperimentSavedMetricsWorkflowInputs:
        return ExperimentSavedMetricsWorkflowInputs(hour=int(inputs[0]))

    @temporalio.workflow.run
    async def run(self, inputs: ExperimentSavedMetricsWorkflowInputs) -> dict:
        if temporalio.workflow.patched("experiment-hourly-chunked-2026-10"):
            return await _run_hourly_chunked(
                get_experiment_saved_metrics_page,
                calculate_experiment_saved_metric,
                inputs,
                lambda continuation: ExperimentSavedMetricsWorkflowInputs(hour=inputs.hour, continuation=continuation),
            )

        # Everything below is replay-only for executions recorded before the chunked path shipped.
        run_started_at = temporalio.workflow.now()

        # Step 1: Discover experiment-saved metrics for this hour
        experiment_metrics = await temporalio.workflow.execute_activity(
            get_experiment_saved_metrics_for_hour,
            inputs.hour,
            start_to_close_timeout=timedelta(minutes=5),
            retry_policy=RetryPolicy(maximum_attempts=3),
        )

        if not experiment_metrics:
            return {
                "hour": inputs.hour,
                "total": 0,
                "succeeded": 0,
                "failed": 0,
                "recalculations_synced": 0,
            }

        # Step 2: Per experiment, calculate its metrics and publish its recalculation as soon as they
        # finish, so a team's results land minutes after its own experiments compute instead of hours
        # after the whole batch. The patch gates keep replay of older histories deterministic.
        semaphore = asyncio.Semaphore(MAX_CONCURRENT_METRICS)

        if temporalio.workflow.patched("experiment-per-experiment-publish-2026-09"):
            results, recalculations_synced = await _calculate_and_publish_per_experiment(
                calculate_experiment_saved_metric, experiment_metrics, run_started_at, semaphore
            )
        else:

            async def _run_metric(em):
                async with semaphore:
                    return await temporalio.workflow.execute_activity(
                        calculate_experiment_saved_metric,
                        args=[em.experiment_id, em.metric_uuid, em.fingerprint],
                        start_to_close_timeout=timedelta(minutes=15),
                        retry_policy=RetryPolicy(
                            maximum_attempts=TIMESERIES_METRIC_MAX_ATTEMPTS,
                            initial_interval=timedelta(seconds=10),
                            maximum_interval=timedelta(seconds=60),
                        ),
                    )

            tasks = [_run_metric(em) for em in experiment_metrics]
            results = await asyncio.gather(*tasks, return_exceptions=True)

            recalculations_synced = 0
            if temporalio.workflow.patched("experiment-timeseries-recalculation-sync-2026-09"):
                recalculations_synced = await _create_recalculations_from_timeseries(
                    {(em.experiment_id, em.team_id) for em in experiment_metrics if em.team_id is not None},
                    run_started_at,
                    semaphore,
                )

        # Step 3: Summarize
        succeeded = 0
        failed = 0

        for result in results:
            if isinstance(result, BaseException):
                failed += 1
            elif result.success:
                succeeded += 1
            else:
                failed += 1

        _record_publish_outcome(succeeded, recalculations_synced)

        return {
            "hour": inputs.hour,
            "total": len(experiment_metrics),
            "succeeded": succeeded,
            "failed": failed,
            "recalculations_synced": recalculations_synced,
        }


@temporalio.workflow.defn(name="experiment-timeseries-recalculation-workflow")
class ExperimentTimeseriesRecalculationWorkflow(PostHogWorkflow):
    @staticmethod
    def parse_inputs(inputs: list[str]) -> ExperimentTimeseriesRecalculationWorkflowInputs:
        return ExperimentTimeseriesRecalculationWorkflowInputs(recalculation_id=inputs[0])

    @temporalio.workflow.run
    async def run(self, inputs: ExperimentTimeseriesRecalculationWorkflowInputs) -> dict:
        return await temporalio.workflow.execute_activity(
            backfill_experiment_metric,
            inputs.recalculation_id,
            start_to_close_timeout=timedelta(hours=3),
            retry_policy=RetryPolicy(maximum_attempts=3, initial_interval=timedelta(minutes=5)),
            heartbeat_timeout=timedelta(minutes=20),
        )
