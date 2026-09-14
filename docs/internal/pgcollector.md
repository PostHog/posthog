# pgcollector — Postgres telemetry collector

`rust/pgcollector` scrapes telemetry from our RDS/Aurora clusters (pg*stat*\*,
Aurora stat functions, `pg_proctab`, CloudWatch-exported logs) into a stats
Postgres. `rust/pgapi`
([pgapi.md](pgapi.md)) serves the data. Design, catalog and deployment details
live in the crate: [`DESIGN.md`](../../rust/pgcollector/DESIGN.md),
[`docs/deploy.md`](../../rust/pgcollector/docs/deploy.md),
[`docs/telemetry-sources.md`](../../rust/pgcollector/docs/telemetry-sources.md).

## Contract

- **Inputs**: one `pg_monitor`-tier user per monitored cluster, discovered from
  `PGCOLLECTOR_SERVER_<ID>_URL` / `_READER_URL` / `_LOG_GROUP` env vars (one
  golden-chart `psql:` entry per cluster), plus a TOML config for the sink and
  defaults. `pgbouncer: false` everywhere: sessions set GUCs.
- **Output**: partitioned `ts_*` time series, `cur_*` current state, `events`,
  `collector_runs` in the stats database, daily partitions, `retention_days`.
  A collector adds columns to its table when its SELECT gains a column.
- **Load**: every session runs with `statement_timeout = 5s` /
  `lock_timeout = 1s`; per-collector cost is tabulated in `docs/deploy.md`
  "Load profile". Per-backend collectors ship off by default.
- **Security**: TLS required for sink and targets unless the URL says
  `sslmode=disable`/`prefer`; the collector's own statements are kept out of
  the server log; statement text taken from logs and `pg_stat_activity` is
  stored with string literals redacted; `pg_stat_statements` text is already
  normalised by Postgres.
- **Ops**: `/healthz`, `/readyz`, `/metrics` on `:9187`; `--check`, `--once`,
  `--parse-log` for validation.
