# PostHog Dagster DAGs

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
3. Import and register them in the relevant file in `dags/locations/`
4. Add appropriate tests in the `tests/` directory

## Running Tests

Tests are implemented using pytest. The following command will run all DAG tests:

```bash
# From the project root
pytest dags/
```

To run a specific test file:

```bash
pytest dags/tests/test_exchange_rate.py
```

To run a specific test:

```bash
pytest dags/tests/test_exchange_rate.py::test_name
```

Add `-v` for verbose output:

```bash
pytest -v dags/tests/test_exchange_rate.py
```

### Web Analytics Pre-Aggregated Tables

**Note:** For materializing web analytics preaggregated tables locally (e.g., during development or testing), you may want to use a higher partition count to process more data in a single run:

```bash
DAGSTER_WEB_PREAGGREGATED_MAX_PARTITIONS_PER_RUN=3000 DEBUG=1 dagster dev -m dags.definitions
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
export DAGSTER_HOME=$(pwd)/.dagster_home && DAGSTER_WEB_PREAGGREGATED_MAX_PARTITIONS_PER_RUN=1 DEBUG=1 dagster dev -m dags.definitions
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
For posthog employees, it is on our charts repo: https://github.com/PostHog/charts/blob/master/config/dagster

## Additional Resources

- [Dagster Documentation](https://docs.dagster.io/)
- [PostHog Documentation](https://posthog.com/docs)
