<!-- markdownlint-disable MD013 -->

# Logs sampling — rollout runbook

Complements `docs/internal/logs-sampling-discovery.md` with operator rollout steps.

## Feature flags and gates

- **API / UI:** flag `logs-sampling-rules` (see `FEATURE_FLAGS.LOGS_SAMPLING_RULES`). When off, rules API
  is unavailable and configuration UI is hidden.
- **Ingestion:** env `LOGS_SAMPLING_ENABLED_TEAMS` (team IDs, `*` for all, empty disables). Use
  `LOGS_SAMPLING_KILLSWITCH=true` to stop evaluation without redeploying rules.

Roll out **UI/API first**, then widen the worker allowlist. Otherwise Postgres has rules that ingestion
ignores until allowlisted.

## Rollout sequence

1. Enable the flag internally; verify CRUD and Services tab (severity mix, share, rules).
2. Allowlist one low-traffic team; watch sampling drop counter and DLQ.
3. Expand allowlist by segment; document killswitch in the change record.
4. When ClickHouse-backed simulate exists, replace the stub and re-check the estimate card.

## Monitoring

- Counters: sampling records dropped by team; message drops with reason `sampling_all_dropped`.
- Latency: ingestion histograms after enabling sampling (decode/encode when rules are non-empty).

## Rollback

1. `LOGS_SAMPLING_KILLSWITCH=true` (immediate).
2. Clear or narrow `LOGS_SAMPLING_ENABLED_TEAMS`.
3. Disable or delete rules in UI if needed (worker cache TTL ~30s).

## Dashboards (suggested)

- Sum drops by `team_id` (cap cardinality).
- Ratio of sampling drops to allowed records / volume.
- Alert on DLQ spikes after a sampling change.

## Gradual rollout checklist

- [ ] Sign-off on discovery assumptions (passthrough with no enabled rules, `team_id` scope).
- [ ] Dogfood severity rules before `path_drop` regex.
- [ ] Link runbook from internal logs on-call doc if applicable.
- [ ] Post-mortem template if a rule is too aggressive (disable rule + killswitch).
