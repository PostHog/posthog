# PROTOTYPE — SQL insight filter overrides (throwaway, do not merge)

**Question:** SQL insights that use `{filters}` can only be filtered by editing the insight. What should setting view-time filter overrides look like?

**Plan:** Three variants on the existing insight view route (`/insights/<short_id>`), switchable via `?variant=`, with a floating bottom bar.

## Run

```bash
./bin/start   # or hogli start
```

Open any saved SQL insight that uses `{filters}` and append `?variant=A`:

```text
http://localhost:8010/project/<id>/insights/<short_id>?variant=A
```

Switch with the floating bottom bar or `←`/`→`. Variants:

- **A — Classic insight card**: the results sit in the real `InsightVizDisplay` card with an `InsightDisplayConfig` header row — the date filter is configured exactly like `InsightDateFilter`, showing the effective range (override if set, else saved), plus property filters. No extra labels. Immediate apply.
- **B — Overrides panel**: page stays clean; one button opens a staged panel showing saved filters next to your overrides, with explicit Apply/Clear. Deliberate, diff-oriented.
- **C — Editable summary**: a prose line ("Showing … where …") whose segments edit in place. Zero chrome until you interact.

## How it works (no new plumbing)

All variants write the existing `?filters_override=` URL param — the same mechanism dashboards use when you open a tile. `insightSceneLogic` picks it up, the insight API applies it server-side into `{filters}`, and the existing "viewing with overrides" banner + Discard button keep working. Nothing is persisted; results really re-run.

Semantics worth knowing when judging the variants (from `HogQLQueryRunner.apply_dashboard_filters`):

- an override date range **replaces** the saved one
- override properties are **appended** to saved ones
- `filterTestAccounts` is **ignored** for HogQL queries, so no toggle here

## Productionizing notes

The gate (`?variant=` + non-production) and everything in this folder is throwaway. The real feature is roughly: pick a variant, render it in view mode for HogQL-containing insights, write `filters_override` via `urls.insightView`. Backend already done.
