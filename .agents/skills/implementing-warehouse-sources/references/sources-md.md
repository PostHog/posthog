# Updating SOURCES.md

`products/warehouse_sources/backend/temporal/data_imports/sources/SOURCES.md` is the inventory of every registered source, its
communication method, and whether its outbound traffic is tracked. Update it as part of the same PR
whenever you:

- **Add a new source** — initially as a Scaffolded entry; move it into the Implemented table once you
  ship working sync logic.
- **Implement a previously scaffolded source** — move the row into the Implemented table and fill in
  comm method, primary library, and tracked-transport state.
- **Migrate a vendor SDK** to inject a tracked session — flip the source from `⚠️ Vendor SDK` to `✅`.
- **Switch a source's protocol** — e.g. swap REST for gRPC, add webhook support alongside the pull API,
  or move from `requests` to a vendor SDK. Update both the comm method and tracked-transport columns.

Keep the entries alphabetical within each table. The scaffolded list is one source per line (one bullet
each, also alphabetical) so adding or removing a source only touches its own line and avoids conflicts with
concurrent PRs — don't collapse it back into a comma-separated paragraph. If you add a partially-tracked
source, also append a short "Notes on partially-tracked sources" entry explaining what blocks tracking
(e.g. a vendor SDK with no session/interceptor seam).
