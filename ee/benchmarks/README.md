# Clickhouse query benchmarks

This is the benchmark suite for PostHog clickhouse queries. It tracks performance improvements to clickhouse queries over time.

The benchmarks are run using [airspeed velocity](https://asv.readthedocs.io/).

To get stable results over time, a stable clickhouse node which has been pre-filled with data is used to run against.

Historical benchmark results can be found in https://github.com/PostHog/benchmark-results.

# FAQ

## Benchmarking your PRs

Benchmarks run every day against master branch.

If your branch contains significant changes to query performance, add `performance` label to your PR.

An action will then run and comment on the benchmarks on your PR.

## Installation (local)

These benchmarks are run using _airspeed velocity_ so, you need to have
`asv` installed which in turn needs virtualenv (or an anaconda dist),

```bash
pip install asv virtualenv
```

## Running the benchmarks locally

These benchmarks are mostly run in CI for:

- master branch
- PRs labeled with `performance`

To run the all the benchmarks locally, [get access to the clickhouse node](https://github.com/PostHog/vpc/blob/main/client_values/benchmarking/values.yaml) and:

```bash
# Set up machine
asv machine --machine ci-benchmarks --config ee/benchmarks/asv.conf.json
# Replace X with appropriate credentials
CLICKHOUSE_HOST=X CLICKHOUSE_USER=X CLICKHOUSE_PASSWORD=X CLICKHOUSE_DATABASE=posthog asv run --config ee/benchmarks/asv.conf.json
```

You'll probably want to be running one test, with quick iteration. Running e.g.:

```bash
asv run --config ee/benchmarks/asv.conf.json --bench track_lifecycle --quick
```

will run any benchmark regex-matching `track_lifecycle` only once.

See [asv documentation](https://asv.readthedocs.io/en/stable/commands.html#asv-run) for additional information.

## Adding new benchmarks

Edit the `benchmarks.py` file as needed. Use `@benchmark_clickhouse` decorator to select tests to run

## Backfilling benchmarks

- Clone `https://github.com/PostHog/benchmark-results` locally under ee/benchmarks/results
- Run something like `CLICKHOUSE_HOST=X CLICKHOUSE_USER=X CLICKHOUSE_PASSWORD=X CLICKHOUSE_DATABASE=posthog asv run --config ee/benchmarks/asv.conf.json --date-period 4d master~500..`
- Run `asv publish` and commit the changes to benchmark-results repo

If you have questions, use benchmark.yml github action as a guide.
