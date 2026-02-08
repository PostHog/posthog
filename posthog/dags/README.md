# Posthog DAGs

This directory contains [Dagster](https://dagster.io/) data pipelines (DAGs) for PostHog. Dagster is a data orchestration framework that allows us to define, schedule, and monitor data workflows.

## What is Dagster?

Dagster is an open-source data orchestration tool designed to help you define and execute data pipelines. Key concepts include:

- **Assets**: Data artifacts that your pipelines produce and consume (e.g., tables, files)
- **Ops**: Individual units of computation (functions)
- **Jobs**: Collections of ops that are executed together
- **Resources**: Shared infrastructure and connections (e.g. database connections)
- **Schedules**: Time-based triggers for jobs
- **Sensors**: Event-based triggers for jobs

## Project Structure

- `locations/`: Main Dagster definition files (split by team) that defines assets, jobs, schedules, sensors, and resources
- `common.py`: Shared utilities and resources
- Individual DAG files (e.g., `exchange_rate.py`, `deletes.py`, `person_overrides.py`)
- `tests/`: Tests for the DAGs

Each individual product can also define their own DAGs on `products/<product>/dags`. They will be instantiated into a location in here. We'll eventually move all of the individual DAGs from this folder to inside one of the products but that's WIP.

### Cloud access for posthog employees

Ask someone on the #team-infrastructure or #team-clickhouse to add you to Dagster Cloud. You might also want to join the #dagster-posthog slack channel.

### Adding a New Team

To set up a new team with their own Dagster definitions and Slack alerts, follow these steps:

1. **Create a new definitions file** in `locations/<team_name>.py`:

   ```python
   import dagster

   from posthog.dags import my_module  # Import your DAGs

   from . import resources  # Import shared resources (if needed)

   defs = dagster.Definitions(
       assets=[
           # List your assets here
           my_module.my_asset,
       ],
       jobs=[
           # List your jobs here
           my_module.my_job,
       ],
       schedules=[
           # List your schedules here
           my_module.my_schedule,
       ],
       resources=resources,  # Include shared resources (ClickHouse, S3, Slack, etc.)
   )
   ```

   **Examples**: See `locations/analytics_platform.py` (simple) or `locations/web_analytics.py` (complex with conditional schedules)

2. **Register the location in the workspace** (for local development):

   Add your module to `.dagster_home/workspace.yaml`:

   ```yaml
   load_from:
     - python_module: posthog.dags.locations.your_team
   ```

   **Note**: Only add locations that should run locally. Heavy operations should remain commented out.

3. **Configure production deployment**:

   For PostHog employees, add the new location to the Dagster configuration in the [charts repository](https://github.com/PostHog/charts) (see `argocd/dagster/`).

   Sample PR: https://github.com/PostHog/charts/pull/6366

4. **Add team to the `JobOwners` enum** in `common/common.py`:

   ```python
   class JobOwners(str, Enum):
       TEAM_ANALYTICS_PLATFORM = "team-analytics-platform"
       TEAM_YOUR_TEAM = "team-your-team"  # Add your team here (alphabetically sorted)
       # ... other teams
   ```

5. **Add Slack channel mapping** in `slack_alerts.py`:

   ```python
   notification_channel_per_team = {
       JobOwners.TEAM_ANALYTICS_PLATFORM.value: "#alerts-analytics-platform",
       JobOwners.TEAM_YOUR_TEAM.value: "#alerts-your-team",  # Add mapping here (alphabetically sorted)
       # ... other teams
   }
   ```

6. **Create the Slack channel** (if it doesn't exist) and ensure the Alertmanager/Max Slack bot is invited to the channel

7. **Apply owner tags to your team's assets and jobs** (see next section)

### How slack alerts works

- The `notify_slack_on_failure` sensor (defined in `slack_alerts.py`) monitors all job failures across all code locations
- Alerts are only sent in production (when `CLOUD_DEPLOYMENT` environment variable is set)
- Each team has a dedicated Slack channel where their alerts are routed based on job ownership
- Failed jobs send a message to the appropriate team channel with a link to the Dagster run

#### Consecutive Failure Thresholds

Some jobs are configured to only alert after multiple consecutive failures to avoid alert fatigue. Configure this in `slack_alerts.py`:

```python
CONSECUTIVE_FAILURE_THRESHOLDS = {
    "web_pre_aggregate_current_day_hourly_job": 3,  # Alert after 3 consecutive failures
    "your_job_name": 2,  # Add your threshold here
}
```

#### Disabling Notifications

To disable Slack notifications for a specific job, add the `disable_slack_notifications` tag:

```python
@dagster.job(tags={"disable_slack_notifications": "true"})
def quiet_job():
    pass
```

#### Testing Alerts Locally

When running Dagster locally (with `DEBUG=1`), the Slack resource is replaced with a dummy resource, so no actual notifications are sent. This prevents test alerts from being sent to production Slack channels during development.

To test the alert routing logic, write unit tests in `tests/test_slack_alerts.py`.

## Local Development

### Environment Setup

Dagster uses the `DAGSTER_HOME` environment variable to determine where to store instance configuration, logs, and other local artifacts. Set this to the .dagster_home file at the top of this repository:

```bash
export DAGSTER_HOME=$(pwd)/.dagster_home
```

You can add this to your shell profile if you want to always store your assets, or to your local `.env` file which will be automatically detected by `dagster dev`.

### Running the Development Server

(Recommended) The Dagster development server starts automatically if you are using the top-level local development script:

```bash
./bin/start.sh
```

To run only the Dagster development server locally:

```bash
export DAGSTER_HOME=$(pwd)/.dagster_home
export DEBUG=1 # Important: Set DEBUG=1 when running locally to use local resources
dagster dev --workspace $DAGSTER_HOME/workspace.yaml
```

The Dagster UI will be available at http://localhost:3000 by default, where you can:

- Browse assets, jobs, and schedules
- Manually trigger job runs
- View execution logs and status
- Debug pipeline issues

## Adding New DAGs

When adding a new DAG:

1. Create a new Python file for your DAG
2. Define your assets, ops, and jobs
3. Import and register them in the relevant file in `posthog/dags/locations/`
4. Add appropriate tests in the `tests/` directory

## Running Tests

Tests are implemented using pytest. You can use your usual `pytest` commands

```bash
# From the project root
pytest posthog/dags/ products/**/dags/
```

### Web Analytics Pre-Aggregated Tables

**Note:** For materializing web analytics preaggregated tables locally (e.g., during development or testing), you may want to use a higher partition count to process more data in a single run:

```bash
DAGSTER_WEB_PREAGGREGATED_MAX_PARTITIONS_PER_RUN=3000 DEBUG=1 dagster dev -m posthog.dags.definitions
```

This will allow backfills to process up to 3000 partitions per run instead of the default, significantly reducing the number of individual runs needed for large historical backfills.

### Testing Concurrency Limits Locally

To test job concurrency limits (useful for jobs like `web_analytics_daily_job` that use backfill policies), you need to configure a `dagster.yaml` file with concurrency settings. This is especially important for asset backfills which create `__ASSET_JOB` runs that can overwhelm your system if not properly limited.

#### Setup

1. Create the Dagster home directory and configuration file:

```bash
mkdir -p .dagster_home
```

2. Create `.dagster_home/dagster.yaml` with the following content:

```yaml
run_coordinator:
  module: dagster._core.run_coordinator.queued_run_coordinator
  class: QueuedRunCoordinator
  config:
    dequeue_interval_seconds: 5

run_launcher:
  module: dagster._core.launcher.default_run_launcher
  class: DefaultRunLauncher

concurrency:
  runs:
    max_concurrent_runs: 10 # Overall instance limit
    tag_concurrency_limits:
      # Limit specific job types
      - key: 'dagster/job_name'
        value: 'web_analytics_daily_job'
        limit: 1
```

3. Run Dagster with the configuration:

````bash
DAGSTER_WEB_PREAGGREGATED_MAX_PARTITIONS_PER_RUN=1  # Force small partitions per run to create multiple runs

```bash
export DAGSTER_HOME=$(pwd)/.dagster_home && DAGSTER_WEB_PREAGGREGATED_MAX_PARTITIONS_PER_RUN=1 DEBUG=1 dagster dev -m posthog.dags.definitions
````

#### Testing

1. In the Dagster UI, navigate to your assets (e.g., web analytics assets)
2. Start a backfill for several days (e.g., 3-5 days)
3. Check the "Runs" page - you should observe:
   - Only 1 run in `STARTED`/`STARTING` status at a time for the same concurrency group
   - Other runs waiting in `QUEUED` status
   - Runs progressing sequentially: `QUEUED` → `STARTED` → `SUCCESS`

#### Production Configuration

For production deployments, configure similar concurrency settings in your `dagster.yaml`.
For PostHog employees, it is on our charts repo: https://github.com/PostHog/charts/tree/master/argocd/dagster

## Additional Resources

- [Dagster Documentation](https://docs.dagster.io/)
- [PostHog Documentation](https://posthog.com/docs)
