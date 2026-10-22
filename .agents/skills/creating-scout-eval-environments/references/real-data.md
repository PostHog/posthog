# Export a minimal real-data slice

Use current source state, with no synthesized rows. This route works without an
old Scout run. Use a saved Scout or a private draft `SKILL.md` plus target project.

## Choose scope before exporting

Read the task, referenced skills, config, active notes, memory cursor and comparison
windows. Discover required tables and properties through source tools. Include the
whole selected cohort: successful events as well as errors when a denominator
matters, related rows for joins, and historical windows used for comparisons.
Do not filter to only the rows that support an expected finding.

Save a private JSON matching
`products/signals/backend/scout_harness/eval_environment/source_plan.py`:

- `environment_id`, `project_id`, `skill_name`, and explicit UTC `source_cutoff`.
- `event_windows`: half-open UTC bounds, exact event names and optional property
  equality sets. Windows are unioned without duplicating rows. Empty windows are
  allowed only when events are not a dependency.
- `metric_names`: explicitly selected governed metrics over events only.
- `history_from`: recent run history; active notes and durable memory are not
  limited by this date. Their referenced older runs are included as well.
- `report_ids` and optional `memory_keys`: a justified selection for deduplication
  and steering. Omit `memory_keys` to preserve all active project memory; `[]`
  explicitly selects none. Do not use an empty list to hide a missing dependency.
- `dependencies` and `selection_reason`: describe the full task scope. Supported
  dependency names are `events`, `data_catalog_metrics`, and `scout_context`.
  Declare required unsupported surfaces too; validation rejects them explicitly.
- `users`: source-verified identity details needed to resolve note authors or
  metric ownership when the API exposes only a name/email. Never invent them.
- `time_strings`, `string_replacements`, `text_time_policy_reviewed`: review embedded
  dates and project links, and declare exact mappings. Typed timestamps shift
  automatically; arbitrary text does not. Keep concrete windows in `steering`.
- `max_events`, `max_context_rows`, `page_size`: operational limits, never sampling
  instructions. Exceeding them fails the export.

For a new scout, set `draft_skill` to the private `SKILL.md` and use `draft_config`
for intended config. No prior Scout run is required. Source context still comes
from the selected project; absent history is legitimate, invented history is not.
Draft skill files must be readable text; binary dependencies need another adapter.

## Current source API limits

The exporter uses existing read APIs. It cannot assume all source objects are
represented by the bundle schema. Check companion skills, warehouse tables,
people/groups, reviewer rosters, external tools, report assignments and linked
pull requests before export. Stop with the concrete missing dependency instead of
stripping it or implementing a new adapter during routine skill use. Metrics can
be queried by name; source metric UUIDs embedded in Scout context are currently
unsupported because that context cannot yet bind their restored IDs.

A runnable Scout export currently requires `profile_snapshot`: a private JSON
containing `source_origin`, `project_id`, `captured_at` and the complete stored
`profile` (`profile_id`, `computed_at`, `expires_at`, `source_version`, `payload`).
It must match the selected project, precede the cutoff and remain unexpired there.
Do not fabricate this snapshot. The ordinary profile GET can queue a rebuild on a
cache miss, so the exporter does not call it. If no verified snapshot is available,
report this limitation; a future source API with a guaranteed read-only cache
endpoint can remove that manual input.

Source APIs are not a cross-database historical snapshot. The exporter makes two
complete reads of selected events and context and rejects observed changes. This
detects changes during export, not every possible concurrent write. For a changing
source, retry with a fresh cutoff; do not silently treat current context as older
state. Row limits and unresolvable pagination ties fail closed.

## Export and package

Use a source read token in a named environment variable available inside the
repository wrapper. Do not put its value in command arguments, the plan, logs or
the bundle. Source API access is separate from local gateway/model credentials.

```sh
.codex/with-flox python -m products.signals.backend.scout_harness.eval_environment.source \
  --source https://us.posthog.com --token-env SOURCE_POSTHOG_READ_TOKEN \
  --plan /private/source-plan.json --output /private/export-v1
```

A successful Scout export writes `events.parquet`, `metrics.parquet`, `case.json`,
`source-plan.json` and `source-provenance.json`. It refuses to replace an existing
output. Provenance records selection, content hashes, source reads, identity
mappings and zero synthesized rows. Memory keys and draft skill names receive
stable local record IDs; their content remains source-backed.

The explicit `purpose="events_only"` mode is useful to check a data export. It
produces no scout case and cannot satisfy a request for a runnable Scout
environment. Never switch to it as an automatic fallback.

Write the case's `time_strings` and `string_replacements` into a private text-policy
JSON, then pack. The case and manifest must agree on name, cutoff, timezone and
text policy:

```sh
.codex/with-flox python -m products.posthog_ai.eval_harness.environment pack \
  --events /private/export-v1/events.parquet \
  --metrics /private/export-v1/metrics.parquet \
  --scout-case /private/export-v1/case.json \
  --source-cutoff <source-cutoff> --name <environment-id> \
  --timezone <source-timezone> --text-policy /private/text-policy.json \
  --output /private/bundle/environment.tar.gz
```

Keep the plan and provenance beside the archive as private operator evidence.
The archive carries only the restore inputs, not credentials or reference answers.
`pack` validates the complete attachment and its relationships before publishing
the archive and SHA-256. It does not start services or make model calls.

Inspect counts and representative task queries against the selected source scope.
A byte-identical archive is not required across export times: source state and the
cutoff can change. For unchanged captured inputs, canonical rows and IDs are
stable. Preserve each accepted bundle as an immutable version.

Continue with [validation and lifecycle](validation.md). A supported portable
bundle restores the pinned skill and context, then freezes them automatically.
Native mode uses the regular Scout prompt builder; it needs no recorded prompt.
