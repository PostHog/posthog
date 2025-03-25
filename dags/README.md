# PostHog Dagster DAGs

This directory contains [Dagster](https://dagster.io/) data pipelines (DAGs) for PostHog. Dagster is a data orchestration framework that allows us to define, schedule, and monitor data workflows.

## What is Dagster?

Dagster is an open-source data orchestration tool designed to help you define and execute data pipelines. Key concepts include:

-   **Assets**: Data artifacts that your pipelines produce and consume (e.g., tables, files)
-   **Ops**: Individual units of computation (functions)
-   **Jobs**: Collections of ops that are executed together
-   **Resources**: Shared infrastructure and connections (e.g. database connections)
-   **Schedules**: Time-based triggers for jobs
-   **Sensors**: Event-based triggers for jobs

## Project Structure

-   `definitions.py`: Main Dagster definition file that defines assets, jobs, schedules, sensors, and resources
-   `common.py`: Shared utilities and resources
-   Individual DAG files (e.g., `exchange_rate.py`, `deletes.py`, `person_overrides.py`)
-   `tests/`: Tests for the DAGs

## Local Development

### Environment Setup

Dagster uses the `DAGSTER_HOME` environment variable to determine where to store instance configuration, logs, and other local artifacts. If not set, Dagster will use a temporary folder that's erased after you bring `dagster dev` down

```bash
# Set DAGSTER_HOME to a directory of your choice
export DAGSTER_HOME=/path/to/your/dagster/home
```

For consistency with the PostHog development environment, you might want to set this to a subdirectory within your project:

```bash
export DAGSTER_HOME=$(pwd)/.dagster_home
```

You can add this to your shell profile if you want to always store your assets, or to your local `.env` file which will be automatically detected by `dagster dev`.

### Running the Development Server

To run the Dagster development server locally:

```bash
# Important: Set DEBUG=1 when running locally to use local resources
DEBUG=1 dagster dev
```

Setting `DEBUG=1` is critical to get it to run properly

The Dagster UI will be available at http://localhost:3000 by default, where you can:

-   Browse assets, jobs, and schedules
-   Manually trigger job runs
-   View execution logs and status
-   Debug pipeline issues

## Adding New DAGs

When adding a new DAG:

1. Create a new Python file for your DAG
2. Define your assets, ops, and jobs
3. Import and register them in `definitions.py`
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

## Additional Resources

-   [Dagster Documentation](https://docs.dagster.io/)
-   [PostHog Documentation](https://posthog.com/docs)
