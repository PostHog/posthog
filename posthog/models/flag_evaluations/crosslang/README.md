# flag_evaluations shared values

`flag_evaluations.json` holds the `flag_evaluations` ClickHouse table's TTL, which Python, Node and Rust all need.

| Key        | Meaning                                                                           |
| ---------- | --------------------------------------------------------------------------------- |
| `ttl_days` | The table's TTL. A row dated day D expires when day D + `ttl_days` starts in UTC. |

## Who reads it

- Python reads this file at runtime as `FLAG_EVALUATIONS_TTL_DAYS` in `posthog/models/flag_evaluations/sql.py`.
- The Node fork step mirrors `ttl_days` as `FLAG_EVALUATIONS_TTL_DAYS` in `nodejs/src/ingestion/common/steps/event-processing/fork-flag-evaluations-step.ts`.
- The cohort seeder mirrors `ttl_days` as `FLAG_EVALUATIONS_TTL_DAYS` in `rust/cohort-seeder/src/domain/pinned.rs`.

The Rust image build context is `rust/` and the Node build compiles from `nodejs/`, so neither can read this file at runtime.

## How to change a value

1. Edit this file first.
2. Update each mirror listed above.
3. Add a ClickHouse migration for the existing table. The comment above `FLAG_EVALUATIONS_TTL_DAYS` in `sql.py` says why.
