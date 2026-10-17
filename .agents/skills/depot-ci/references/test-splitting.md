# Depot CI test reporting and timing-based splitting

Use this reference when configuring JUnit reporting or splitting a test suite across Depot CI matrix jobs. For listing existing results with `depot tests <id>`, use `runs-and-debugging.md`.

## Requirements

`depot tests split`, `depot tests run`, and `depot tests report` work only inside Depot CI or Depot GitHub Actions runner jobs. Depot CI authenticates automatically. On Depot GitHub Actions runners, grant `id-token: write`.

Depot balances shards with historical JUnit durations. Filename candidates without timing history use file size. Other candidates use deterministic fallback weights until reports provide timing data.

## Recommended workflow action

`depot/tests-run-action@v1` wraps selection, execution, and JUnit upload. In Depot CI matrix jobs, omitted shard inputs use `DEPOT_MATRIX_JOB_INDEX` and `DEPOT_MATRIX_JOB_TOTAL`.

```yaml
jobs:
  test:
    runs-on: depot-ubuntu-24.04
    strategy:
      fail-fast: false
      matrix:
        shard: [0, 1, 2, 3]
    steps:
      - uses: actions/checkout@v4
      - uses: depot/tests-run-action@v1
        with:
          candidates-command: go list ./...
          command: mkdir -p reports && xargs gotestsum --junitfile reports/junit.xml --
          report-path: reports/junit.xml
```

On Depot GitHub Actions runners, pass `index: ${{ strategy.job-index }}` and `total: ${{ strategy.job-total }}` explicitly. Set explicit values in multi-axis matrices when only one axis defines the intended shards.

## Candidate identity and timing granularity

A candidate is one unit accepted by the test command. Use `filename` when candidates match the JUnit `file` field. Use `classname` when candidates match the JUnit `classname` field.

The CLI infers `filename` for recognized source or test-file paths and `classname` otherwise. Set `--candidate-type` when the apparent identity differs from the JUnit field. Vitest and Playwright commonly need `classname` even when their candidates look like file paths.

`--timings-type` defaults to the candidate identity. Use `testname` to calculate each candidate's duration from individual JUnit test cases.

## Commands

### `depot tests split`

Print the candidates assigned to one shard. Provide candidates with standard input, `--candidates-file`, or `--candidates-command`.

```bash
depot tests split \
  --candidates-command 'go list ./...' \
  --index 0 --total 4 \
  --timings-type testname
```

### `depot tests run`

Select a shard, run a command with the candidates on standard input, and upload the JUnit reports. The command preserves the test command's exit code and attempts report upload after failures.

```bash
depot tests run \
  --candidates-command 'go list ./...' \
  --index 0 --total 4 \
  --timings-type testname \
  --command 'xargs gotestsum --junitfile reports/junit.xml --' \
  --report-path reports/junit.xml
```

Set `--total 1` to run all supplied candidates, including inside a matrix. Use `--split-key` only to separate logical suites that would otherwise share timing assignments. Use `--report-key` only when one job uploads more than one independent report.

### `depot tests report`

Upload JUnit XML that another command already created. Provide report paths as positional arguments or repeat `--report-path`.

```bash
depot tests report reports/junit.xml --key unit-tests
```

When a workflow uploads reports directly with `depot/test-report-action@v1`, use `if: ${{ !cancelled() }}` so failed test steps still produce results.
