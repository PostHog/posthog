# Experiment metrics calculation

This module calculates experiment metrics in the background using Temporal, a workflow orchestration system. It runs daily for each active experiment, computing statistical results and storing them for timeseries retrieval.

## How it works

Each team can configure when their experiments should be recalculated (default: 2 AM UTC). The system runs 24 schedules - one for each hour of the day. When a schedule fires, it finds all experiments belonging to teams configured for that hour and calculates their metrics.

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

1. Discovers which experiment-metric pairs need calculation
2. Calculates each metric in parallel
3. Stores results in the database
4. Assembles one completed metrics recalculation per experiment from the points this run wrote (see below)

### Handing fresh points to the recalculation reader

The experiment page reads results through `GET /metrics_recalculation/latest`, which returns the newest completed `ExperimentMetricsRecalculation`. Timeseries rows alone never reach it, so after the metric activities finish, each workflow runs `create_recalculation_from_timeseries` once per experiment it touched (`products/experiments/backend/timeseries_sync.py`):

- A metric qualifies when its newest completed row under the config fingerprint has a `query_to` between the workflow start and now. Yesterday's row for a metric that failed today does not qualify, and neither does a future-dated day-end row from the backfill workflow.
- The activity creates a completed recalculation with trigger `timeseries_sync` and copies each qualifying row under the recalc fingerprint at one shared `query_to`, one second past the newest point. Copies at a point's own `query_to` would share the `(experiment, metric_uuid, query_to)` key with the timeseries row and rewrite its fingerprint.
- A supported metric without a qualifying point is counted in `total_metrics` but gets no copy, so the frontend sees the gap and heals it with a real run. Metric types the daily run cannot compute (`DAILY_TIMESERIES_METRIC_TYPES` in `metric_resolution.py`, which excludes retention) are left out of `total_metrics` and `metric_uuids` entirely.
- The row belongs to the experiment's daily run, not to one workflow. The inline and saved metric workflows both run the activity for the same experiment in the same hour, each with its own run start. The first pass creates the row; a later pass finds the day's `timeseries_sync` row and adds the copies it still lacks, so the row covers every metric the daily run computed whichever workflow finishes last.
- When no sync row exists for the day, the activity skips if any other recalculation, finished or executing, already has a `query_to` at or past the oldest qualifying point.

Each metric stamps its own `query_to` at the moment its activity runs, so the points of one run are seconds to minutes apart. The copies present them as one window; that approximation is deliberate.

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
