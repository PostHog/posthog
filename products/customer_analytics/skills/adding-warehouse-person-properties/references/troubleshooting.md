# Troubleshooting a warehouse property mapping

Start with `custom-property-sources-list` for the source's status, then
`custom-property-sources-runs-list` for its run history. Between them they explain nearly every case.

## Reading the run counts

Each run reports a funnel. Read it left to right and stop at the first number that drops to zero.

| Count                    | Meaning                                                   | Zero means                                                      |
| ------------------------ | --------------------------------------------------------- | --------------------------------------------------------------- |
| `rows_read`              | Rows the run read from the table                          | The table synced nothing, or the sync itself failed             |
| `changed`                | Rows whose mapped values differ from the last snapshot    | Nothing changed since the previous run. Normal on a quiet table |
| `existing`               | Changed rows whose key resolved to a real person or group | The key column does not hold identifiers PostHog knows          |
| `produced`               | Update intents sent onward                                | Rare if `existing` is non-zero. Check `error`                   |
| `skipped_missing_person` | Changed rows dropped because the key did not resolve      | Nothing to fix                                                  |

## Common cases

**Runs complete, but no property appears on anyone.**
Look at `skipped_missing_person`. If it is close to `changed`, the key column is wrong. It usually holds an
internal database ID rather than the distinct ID the SDK sends, or the group key for the chosen group type.
Sample the column and compare against real identities. `key_column` is editable with
`custom-property-sources-partial-update`, so fix it and backfill.

**The property is on the person but does not appear in filter dropdowns yet.**
Property definitions are created by ingestion when the first `$set` lands, and the sync stamps its warehouse
provenance on the next run. So a brand new property name can be usable on a person before it is offered in a
picker. Wait for one more sync, or type the name in by hand.

**No runs at all.**
Check, in order: the source's `is_enabled`, whether the underlying table is still syncing, and whether the
`warehouse-person-properties` feature is on for the project. A disabled source is skipped silently by design.

**`last_sync_error` is set, or `consecutive_failures` is climbing.**
Read the error text on the source and on the most recent run. Treat a failing underlying warehouse sync as
the first suspect, because the property update rides off that sync. Diagnose that with
`diagnosing-failed-warehouse-syncs` before touching the mapping.

**"Sync now" is rejected with a monthly sync limit message.**
`custom-property-sources-sync` runs a real, billable import, so it honors the team's sync pause the same way
the warehouse reload and resync endpoints do. Use `custom-property-sources-backfill` instead. Backfill
re-reads data already in the warehouse, so it works while syncing is paused and costs nothing.

**Values look stale after fixing the warehouse data.**
An incremental sync only stages rows it considers changed, and the property sync also diffs against its own
snapshot. If a correction did not move the source row's incremental field, run a backfill, which reads the
whole table.

**A mapping wrote wrong values and was deleted.**
Deleting a source or definition stops future writes. It never removes properties already on people or
groups. Recreate the mapping with correct values and backfill so the new values overwrite the old ones. There
is no bulk delete of a person property through this feature.

**Group tools return a permission error.**
Group-target definitions, sources, and runs need `group:read` for reads and `group:write` for writes, on top
of the account scopes. Account scope alone is not enough. Creating any person or group mapping also needs
warehouse source editor access, because enabling a mapping drives a billable source.
