# Experiment metrics calculation

This module calculates experiment metrics in the background using Temporal, a workflow orchestration system. It runs on each team's schedule (once or twice per day) for each active experiment, computing statistical results and storing them for timeseries retrieval.

## How it works

Each team can configure one or two times of day when their experiments are recalculated, at least six hours apart (default: once at 02:00 UTC), via `TeamExperimentsConfig.experiment_recalculation_times`. The system runs 24 schedules - one for each hour of the day. Each schedule starts between 2 and 32 minutes past its hour, so the runs do not pile up with other jobs at minute zero. When a schedule fires, it finds all experiments belonging to teams configured for that hour and calculates their metrics. A team with two configured times matches two schedules, so its experiments get two independent runs a day.

```text
┌─────────────────────────────────────────────────────────────────────────┐
│                         Temporal schedules                              │
│                                                                         │
│   Hour 0        Hour 1        Hour 2        ...        Hour 23          │
│   ┌─────┐       ┌─────┐       ┌─────┐                  ┌─────┐          │
│   │00:00│       │01:00│       │02:00│                  │23:00│          │
│   └──┬──┘       └──┬──┘       └──┬──┘                  └──┬──┘          │
│      │             │             │                        │             │
│      ▼             ▼             ▼                        ▼             │
│   Teams A       Teams B       Teams C                 Teams X           │
│   configured    configured    configured              configured        │
│   for 00:00     for 01:00     for 02:00               for 23:00         │
└─────────────────────────────────────────────────────────────────────────┘
```

## Workflow structure

There are two parallel workflow systems:

- **Regular metrics** (`ExperimentRegularMetricsWorkflow`): Processes metrics defined inline in `experiment.metrics` and `experiment.metrics_secondary`
- **Saved metrics** (`ExperimentSavedMetricsWorkflow`): Processes reusable metrics linked via `ExperimentToSavedMetric`

When a schedule triggers, it starts a workflow that:

1. Discovers which experiment-metric pairs need calculation. It skips the metrics that `is_scheduled_metric` rejects, the same as recalculation discovery: legacy metrics without a `metric_type`, and metrics without a uuid
2. Calculates each experiment's metrics in parallel, under one hour-wide concurrency limit
3. Stores results in the database

These workflows used to publish a `timeseries_sync` recalculation row per experiment as well.
The scheduled recalculation workflow owns that job now, so the publish pass is gated out behind
`experiment-drop-timeseries-publish-2026-10`.
An execution that started before that patch keeps the old publish path, so its replay still finds
the activities its history recorded.

```text
┌────────────────────────────────────────────────────────────────────────────┐
│                    ExperimentRegularMetricsWorkflow                        │
│                                                                            │
│  ┌──────────────────────────────────────────────────────────────────────┐  │
│  │  Activity: get_experiment_regular_metrics_for_hour                   │  │
│  │                                                                      │  │
│  │  Find all experiments for teams scheduled at this hour               │  │
│  │  Returns: [(exp_id, metric_uuid, fingerprint), ...]                  │  │
│  └──────────────────────────────────────────────────────────────────────┘  │
│                                    │                                       │
│                                    ▼                                       │
│  ┌──────────────────────────────────────────────────────────────────────┐  │
│  │  Activity: calculate_experiment_regular_metric (runs in parallel)    │  │
│  │                                                                      │  │
│  │  ┌─────────────┐  ┌─────────────┐  ┌─────────────┐                   │  │
│  │  │ Experiment 1│  │ Experiment 1│  │ Experiment 2│  ...              │  │
│  │  │ Metric A    │  │ Metric B    │  │ Metric A    │                   │  │
│  │  └─────────────┘  └─────────────┘  └─────────────┘                   │  │
│  │                                                                      │  │
│  │  Each metric calculation:                                            │  │
│  │  1. Load experiment config                                           │  │
│  │  2. Run ExperimentQueryRunner                                        │  │
│  │  3. Store result in ExperimentMetricResult table                     │  │
│  └──────────────────────────────────────────────────────────────────────┘  │
│                                    │                                       │
│                                    ▼                                       │
│                         Return summary stats                               │
│                    (total, succeeded, failed counts)                       │
└────────────────────────────────────────────────────────────────────────────┘
```

The `ExperimentSavedMetricsWorkflow` follows the same structure but:

- Uses `get_experiment_saved_metrics_for_hour` to discover metrics from `experimenttosavedmetric_set`
- Uses `calculate_experiment_saved_metric` to process each saved metric
- Does not filter on empty `metrics`/`metrics_secondary` arrays (saved metrics are separate)

### Scheduled recalculations

The workflows above write timeseries points, which the recalculation reader never sees on their own.
A separate workflow starts a real recalculation for each eligible experiment, on one hourly schedule
(`products/experiments/backend/temporal/schedule.py`).

That schedule fires at `:30`, after the timeseries runs earlier in the hour, and carries no input.
Discovery reads the hour and selects the teams configured for it, so one schedule serves all 24
hours. A team may configure up to two times, at least 6 hours apart, and gets a run at each.
Both this discovery and the timeseries one call `recalculation_hour_filter`, so the two always
agree on which teams belong to a given hour.

The coordinator selects experiments with the same rules the daily discovery uses, plus a 12-hour
minimum age, an organization feature flag, and a 50-exposure floor. It then starts an ordinary
`ExperimentMetricsRecalculationWorkflow` per experiment, through the same function the API uses.

The timeseries workflows keep one schedule per hour, because each runs its own metric queries and
can outlive its hour. This one starts other workflows and returns, so a single schedule with a
`SKIP` overlap policy covers it.

It skips an experiment whose recalculation is already running, or whose last one finished within
the hour. That freshness check ignores `timeseries_sync` rows: new timeseries executions no longer
write them, and the rows from before that change are still on file.

The coordinator never waits for the runs it starts. Each run's outcome lands on its own
`ExperimentMetricsRecalculation` row, and the `experiment scheduled recalculation started` and
`experiment scheduled recalculation skipped` events carry the coordinator's own decisions.

## Key concepts

**Workflow**: A durable function that orchestrates the calculation. If it fails partway through, Temporal can resume it from where it left off.

**Activity**: A single unit of work (like "find experiments" or "calculate one metric"). Activities can be retried independently if they fail.

**Schedule**: A cron-like trigger that starts workflows at specified times. We use 24 separate schedules (one per hour) rather than a single hourly schedule. This way, if a workflow runs longer than an hour, we don't need to deal with overlap policies.

## Local development

**Temporal UI:** http://localhost:8081

**Create regular metrics schedules locally** (paste into `python manage.py shell`):

```python
import asyncio
from posthog.temporal.common.client import async_connect
from posthog.temporal.common.schedule import a_delete_schedule
from posthog.temporal.experiments.schedule import create_experiment_regular_metrics_schedules

OLD_SCHEDULE_ID_PREFIX = "experiment-metrics-hour"

async def delete_old_schedules(client):
    for hour in range(24):
        schedule_id = f"{OLD_SCHEDULE_ID_PREFIX}-{hour:02d}"
        try:
            await a_delete_schedule(client, schedule_id)
            print(f"Deleted old schedule: {schedule_id}")
        except Exception:
            pass

async def main():
    client = await async_connect()
    print("Deleting old schedules...")
    await delete_old_schedules(client)
    print("Creating new schedules...")
    await create_experiment_regular_metrics_schedules(client)
    print("Done!")

asyncio.run(main())
```

**Create saved metrics schedules locally** (paste into `python manage.py shell`):

```python
import asyncio
from posthog.temporal.common.client import async_connect
from posthog.temporal.experiments.schedule import create_experiment_saved_metrics_schedules

async def main():
    client = await async_connect()
    print("Creating saved metrics schedules...")
    await create_experiment_saved_metrics_schedules(client)
    print("Done!")

asyncio.run(main())
```
