# PostHog-to-PostHog event mirroring

Customers sometimes ask to combine data from two PostHog projects — for example, funnelling users from a product in one project into a product in another. This is what is and is not possible today.

## Queries cannot cross a project boundary

Every ClickHouse-bound HogQL query gets a mandatory `team_id = <current team>` predicate injected at print time: `team_id_guard_for_table` in `posthog/hogql/printer/clickhouse.py`, applied to each selected table by `_ensure_team_id_where_clause` in `posthog/hogql/printer/base.py`, and pushed into the `ON` clause for LEFT JOINs so join shape cannot escape it. Insights and funnels run through the same printer, so a cross-project funnel is structurally impossible.

"Copy to another project" (`posthog/models/resource_transfer/`) duplicates definitions — dashboards, insights, flags — not data, so it does not help here either.

Lifting that boundary is a tenancy-model decision, not a configuration option.

## What does not work

- **A realtime destination pointed at another project.** The hidden `template-posthog-capture` destination calls `postHogCapture`, which hardcodes `team_id: invocation.teamId` (`nodejs/src/cdp/services/hog-executor.service.ts`). A hog function can only re-capture into the project it runs in, regardless of what tokens you configure.
- **The managed warehouse connection as a shared query surface.** It exposes warehouse schemas, not another project's events or persons. See [managed warehouse connections in the SQL editor](./managed-warehouse-sql-editor.md).

## What does work: an HTTP batch export

The HTTP batch export is the one supported PostHog-to-PostHog pipe. It reads events from the source project and posts them to a capture endpoint using the destination project's API key, which re-ingests them as ordinary events in the destination project. Once they land there, they are queryable like any other event — including in funnels.

Setup, in the source project's data pipeline destinations:

1. Create a batch export with destination type **HTTP**.
2. Pick the **PostHog region** of the destination project. The URL is hard-restricted to `https://us.i.posthog.com/batch/` or `https://eu.i.posthog.com/batch/` (`post_json_file_to_url` in `products/batch_exports/backend/temporal/destinations/http_batch_export.py`) — no other host is accepted.
3. Enter the **destination project token** (the `phc_...` project API key of the project you want the events in).
4. Leave the end date empty so it mirrors continuously. HTTP is one of the few destinations allowed to run with no `end_at` (`products/batch_exports/backend/service.py`).
5. Backfill if the destination project needs history as well as new events.

### Sharp edges to set expectations on

- **Events model only.** The export raises `NotImplementedError` for any model other than `events`, and no custom schema is supported. Persons and sessions cannot be mirrored this way. Event filters on the model do apply, so you can narrow which events get mirrored, but you cannot choose which columns go across — the field set is fixed.
- **Mirrored events are billed twice.** They are re-ingested in the destination project, so they count toward ingested event volume in both projects.
- **Person identity only lines up if distinct IDs match.** Mirroring recreates events with their original `distinct_id`, but person merges, aliases, and person properties do not travel with them. If the two projects identify the same human with different distinct IDs, the mirrored events attach to different persons in the destination project and any cross-product funnel will undercount.
- **It is a copy, not a join.** The destination project ends up with both products' events, which is what makes the funnel possible — but the source project is unchanged, and the two copies drift if the export is paused.
