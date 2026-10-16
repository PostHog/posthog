# Flavors and verbs

Each row compares one key's Postgres state with its ClickHouse state.
"Visible" ClickHouse rows exclude lightweight-deleted ones. A tie at the top version counts as visible, because ClickHouse may return either row.

## Persons

| Flavor                  | Meaning                                                                        | Verb                                                                    |
| ----------------------- | ------------------------------------------------------------------------------ | ----------------------------------------------------------------------- |
| `ghost` / `after_purge` | Live in ClickHouse, absent from Postgres, last written before a known purge    | `restore`, or `fold` when its distinct ids now live on one other person |
| `ghost` / `historical`  | Same, but not dated to a purge                                                 | none (report only)                                                      |
| `ghost` / `team_gone`   | Same, for a deleted team                                                       | none                                                                    |
| `deleted_visible`       | Tombstoned in Postgres at or below a live ClickHouse row                       | `bury`                                                                  |
| `hidden`                | Live in Postgres, the ClickHouse winner is a tombstone                         | `republish`                                                             |
| `swept`                 | Live in Postgres, every ClickHouse row lightweight-deleted                     | `republish`                                                             |
| `stale`                 | Live in Postgres below the ClickHouse version                                  | `merge_stale`                                                           |
| `behind`                | Postgres above ClickHouse                                                      | `republish`                                                             |
| `missing_in_ch`         | Live in Postgres, no ClickHouse row                                            | `republish`                                                             |
| `tie`                   | Several ClickHouse rows at the Postgres version with different content         | `republish`                                                             |
| `blanked`               | The ClickHouse winner is empty and unidentified, an earlier row had properties | `republish`                                                             |
| `no_live_mappings`      | Live in Postgres with no live distinct id                                      | none; also appears in another row's `also`                              |

## Distinct ids (mappings)

| Flavor                    | Meaning                                                                    | Verb                                          |
| ------------------------- | -------------------------------------------------------------------------- | --------------------------------------------- |
| `ghost` / `owner_ghost`   | Live in ClickHouse on a person Postgres lacks, no Postgres row             | follows its owner: `restore`, `fold`, or none |
| `ghost` / `owner_live`    | Live in ClickHouse on a live person, no Postgres row                       | `restore`                                     |
| `ghost` / `owner_deleted` | Same, on a tombstoned person                                               | none                                          |
| `deleted_visible`         | Tombstoned in Postgres at or below a live ClickHouse row                   | `bury`                                        |
| `diverged` / `a_absent`   | Postgres names person B, ClickHouse names A, and A is absent from Postgres | `fold`                                        |
| `diverged` / `a_live`     | Same, and A is live in Postgres                                            | `merge`                                       |
| `diverged` / `a_deleted`  | Same, and A is tombstoned                                                  | `republish`                                   |
| `diverged` / `ambiguous`  | B holds ids of several old persons, or A's ids went to several persons     | none; `fold` or `merge` with `--pair`         |
| `stale`                   | Same owner, ClickHouse above Postgres                                      | `republish`                                   |
| `hidden`                  | Live in Postgres, the ClickHouse winner is a tombstone                     | `republish`                                   |
| `missing_in_ch`           | Live in Postgres, no ClickHouse row                                        | `republish`                                   |
| `stray`                   | Live in Postgres on a tombstoned person                                    | none; ingestion re-attaches it on next event  |

## Groups

A group ties rows that must be repaired together:

- `restore:A`: lost person A and its lost distinct ids.
- `fold:A>B`: lost person A, whose ids live on B in Postgres. It holds A's person row, its diverged ids and its ghost ids. Its rows carry `fold_mode`: `full` when A still has a ghost id to merge from, else `light`.
- `merge:A>B`: live A and live B share ids. B survives.
- `ambiguous:X`: X takes part in more than one pair. Leave it, or repair one chosen pair with `--pair`.

A pair is a group only when neither person takes part in another pair, so a group is always safe to repair as a unit.

## Outcomes

- `would_repair`: a dry run found the key still broken.
- `repaired`, `restored`, `moved`, `folded`, `merged`, `buried`, `tombstoned`, `republished`: the key was written.
- `already_*`: an earlier run wrote it, and this run published it again.
- `undelivered`: the Postgres write happened, but its ClickHouse publish did not land. `--resume` retries the key. A restored person that stays undelivered shows up as `behind` in the next scan, and `republish` publishes it.
- `merge_queued`: `merge_stale` sent properties to ingestion. Run the verb again later.
- `properties_sent`: a light `fold` sent the old person's properties to the survivor. Run `fold` again later.
- `merge_sent` (person) and `awaiting_merge` (ids): `merge` or a full `fold` sent `$merge_dangerously`, and ingestion had not applied it within the wait. Rescan later.
- `skipped_no_alias`: no distinct id of the old person, or of the survivor, could carry the merge event.
- `skipped_no_distinct_id`: `restore` or a full `fold` left a person out, because none of its lost distinct ids is in the run or all of them were claimed since the scan. Rescan.
- `identified_not_carried` (in an action's detail): a light `fold` could not mark the survivor identified, because it has only one distinct id.
- `skipped_changed` and `skipped_not_divergent`: the state moved since the scan. Rescan.
- Any other `skipped_*`: the verb refused on purpose. The name says why.
