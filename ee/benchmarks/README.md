# Clickhouse query benchmarks

This is the benchmark suite for PostHog clickhouse queries. It tracks performance improvements to clickhouse queries over time.

The benchmarks are run using [airspeed velocity](https://asv.readthedocs.io/).

To get stable results over time, a stable clickhouse node which has been pre-filled with data is used to run against.

# Quickstart

## Installation

These benchmarks are run using *airspeed velocity* so, you need to have
``asv`` installed,

```bash
pip install asv
```

## Running the benchmarks

These benchmarks are mostly run in CI for:
- master branch
- PRs labeled with `performance`

To run the all the benchmarks locally, get access to the clickhouse node and:

```bash
# Replace X with appropriate credentials
CLICKHOUSE_HOST=X CLICKHOUSE_USER=X CLICKHOUSE_PASSWORD=X CLICKHOUSE_DATABASE=posthog asv run --config ee/benchmarks/asv.conf.json
```

See [asv documentation](https://asv.readthedocs.io/en/stable/commands.html#asv-run) for additional information.

## Adding new benchmarks

Edit the `benchmarks.py` file as needed. Use `@benchmark_clickhouse` decorator to select tests to run
