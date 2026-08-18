# Management commands

The headless entrypoints. Four commands cover the whole product lifecycle, plus one that seeds data to run them against, and together they are how autoresearch is exercised end to end locally without a browser.

Every command calls the same functions the API and the Temporal activities call. They are thin wrappers, not a parallel implementation, and they should stay that way.

**All of them bypass the `autoresearch` feature flag.** That is why local CLI testing works with no flag setup while the API and UI still need one.

## The five commands

- `autoresearch_train` — create a pipeline and/or launch training.
  `--pipeline-id | --team-id --target --name --horizon --create --stub --user-id --iterations`
  With `--create` it creates the pipeline first. With `--stub` it runs `../training/stub.py` (deterministic, free); without it, the real Claude agent runs in a sandbox and costs roughly a dollar.
  **Use `--stub` for anything that isn't specifically testing the agent.**
- `autoresearch_score` — load the champion, score the inference population, emit `autoresearch_prediction` events.
  `--pipeline-id --dry-run --seed-fixture-bundle --prediction-date --backfill-days`
  `--prediction-date` / `--backfill-days` backdate the emitted events, which is the only way to get matured predictions for online validation without waiting out the horizon.
- `autoresearch_validate` — pre-flight target viability, before committing to a run.
  `--team-id --target --horizon`
  Note there is no `--mode` flag. Note also that `autoresearch_train` does **not** call this, so a target that fails here still trains.
- `autoresearch_validate_online` — realized performance for predictions whose horizon has elapsed.
  `--pipeline-id --dry-run`
- `autoresearch_seed_demo` — write a fresh, learnable dataset into a team so the other four have something to chew on.
  `--team-id --users --days --seed --dry-run`
  600 identified persons by default, a "reports" narrative (`report_created`, `collaborator_invited`, `integration_connected`, `pricing_page_viewed`, `$pageview`) and the target `report_shared`, all timestamped relative to now, plus an action "Shared a report externally" for the action-target path. A latent persona drives both features and target so a real model clears baseline. Persons go to ClickHouse only (same path as `generate_demo_data`), so they won't appear in the persons list. Re-running with the same `--seed` writes the same person ids again; use a new seed to add more people.

## Running them locally

Prefix with `CLICKHOUSE_DATABASE=posthog` and run inside the flox environment:

```bash
CLICKHOUSE_DATABASE=posthog flox activate -- bash -c \
  "python manage.py autoresearch_train --create --team-id <TEAM> --target <EVENT> \
   --name '<NAME>' --horizon 30 --user-id <UID> --stub"
```

The env var is needed because flox only sources `.env` on first activation, so the setting is not otherwise present for a one-shot command.

## Things that bite

- **`--stub` versus real is a money decision, not a speed one.** A real run launches a sandbox agent and spends LLM budget. Default to stub.
- **The real-agent path needs more than an API key.** It runs in a Tasks sandbox, so it needs Tasks access and a working MCP server — if the sandbox agent cannot load the `autoresearch-*` MCP tools it will burn a full run doing nothing and fail with `"Agent recorded no iterations before the run ended."`
- **Check the team id.** Demo data does not reliably live on team 1 or team 2; confirm before targeting.
- **Pick a target with volume.** Conversion-shaped events are rare by nature. Engagement events give far more positives, and autoresearch only trains on identified users, so raw event counts overstate what is available.
- **Hedgebox demo data goes stale.** It is generated once with fixed timestamps, so a "last 30 days" window shrinks every day. `autoresearch_seed_demo` is the fix: its timestamps are relative to now, so re-seed with a new `--seed` when the window empties out.
- **`autoresearch_score` on a fresh pipeline emits nothing** if there is no champion yet — train first.
- **Backdated events vanish silently** when the team has `drop_events_older_than_seconds` set; ingestion drops them as too old.
- A large `--backfill-days` run emits N × population events into Kafka in a tight loop and can knock over a local ingestion consumer. Prefer 10–15 days at a time.
- Ad-hoc scripts that call `sync_execute` directly raise `UntaggedQueryError` — wrap with `tag_queries(product="autoresearch", ...)`. These commands already tag themselves.

## Where the rest of the system meets this package

- `autoresearch_train` → `../training/runner.py` (real) or `../training/stub.py` (`--stub`)
- `autoresearch_score` → `../inference/scoring.py`
- `autoresearch_validate` → `../dataset/validation.py`
- `autoresearch_validate_online` → `../evaluation/online_validation.py`
- `autoresearch_seed_demo` → `posthog.models.person.util.create_person` / `posthog.models.event.util.create_event` (the demo generator's persistence path)

The same functions are reached on the scheduled path via `../temporal/workflows.py`, and on the HTTP path via `../api/views.py`.

## When editing this flow

- **Keep the commands thin.** Logic belongs in the package the command calls, so the scheduled path and the API path get it too. A behavior that only exists in a command will not exist in production.
- Adding a flag that changes modeling behavior is a smell — it means the pipeline definition should carry it instead.
- **If you add a command or change its flags, update this file to match.**
