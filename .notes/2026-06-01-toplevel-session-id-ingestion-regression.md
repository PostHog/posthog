# Top-level `$session_id` (and friends) stopped populating — PROD US — 2026-06-01

**Status: RESOLVED (forward) at 2026-06-02 12:19 UTC.** New events populate normally again.
Fix = MV rebuilt: live US events MV is now `events_json_ws_mv_new` (created 12:19:41 UTC) which
**projects** the 7 columns (EU-style); the broken `events_json_mv_ws` + `_temp` pair were removed.
`writable_events` left bare (fine — the MV now supplies the values). Data confirmed healthy from the
12:00 UTC hour (ramp) / fully by 13:00 UTC.

**REMAINING: backfill the outage gap.** Rows ingested **2026-06-01 22:00 → 2026-06-02 ~12:19 UTC**
(~14h, full 0% from 23:00–11:00) still have empty top-level `$session_id`/`$window_id`/`$group_0..4`
on disk. `properties.*` is intact, so nothing is lost — but the fast columns need the backfill mutation
(see "Backfill the gap" below) before those ~14h of events read correctly via the top-level columns.

---

Originally rode on Incident #880 (`#inc-2026-06-01-lag-in-events_recent-exceeding-30-minutes-impacting-batch-ex`,
channel `C0B7MKC1MCZ`), which was marked _resolved_ on the status page at 02:29 UTC — but this silent
correctness regression was a separate facet that persisted ~10h beyond that, until the 12:19 UTC MV rebuild.

## TL;DR

The events ingestion materialized view on US (`events_json_mv_ws`) was dropped and recreated by the
`dmat` re-apply (migration 0267 / PR #59681) **without projecting the `$`-prefixed extracted columns**.
Those columns exist as **bare `String` (no DEFAULT)** on the `writable_events` Distributed table, so the
MV's omission makes `writable_events` ship an explicit `''`, which **bypasses the `DEFAULT` expression**
on `sharded_events`. Result: top-level columns empty, while `properties.*` is intact.

EU is the control: its MV (`events_json_ws_mv`, old name) **still projects** these columns → EU unaffected.
EU's migration got stuck before the destructive recreate (Paweł in-channel: _"the migration will not go
through, the EU is messed up, we must remove DROP COLUMN"_), so EU kept the good MV.

## Exact blast radius (7 columns)

All are `DEFAULT` on `sharded_events`, **bare** on `writable_events`, **not projected** by the US MV:

- `$session_id`
- `$window_id`
- `$group_0`, `$group_1`, `$group_2`, `$group_3`, `$group_4`

**Spared:** `$session_id_uuid` (it is `MATERIALIZED`, not `DEFAULT`, so an explicit insert can't override it —
confirmed still ~45% populated). This DEFAULT-broken / MATERIALIZED-fine split is the proof of mechanism.

`properties.$session_id` etc. are 100% intact — the SDKs are emitting correctly; this is purely server-side.
Verified version-independent: every lib + version (web 1.378.1 … 1.257.0, react-native, ios, android,
flutter, go, mobile) is uniformly 0% top-level. Not a posthog-js issue.

## Timeline (UTC)

- 21:22 `feat(dmat): re-apply dmat_string column wiring` merged (#59681, `6554d68409a`, Sandy Spicer).
  (NB: this PR had already been reverted once before — see `#inc-2026-05-21`.)
- 22:13 `ALTER TABLE writable_events ADD COLUMN dmat_string_*` begins on ingestion nodes (migration 0267 step 2a).
- 22:15 **hard cutover**: top-level `$session_id`/`$window_id`/`$group_*` → 0% (22:00 partial ~59%).
- 23:02 Incident #880 opened (framed as events_recent lag / batch-export delay).
- 23:07–23:48 team "resurrects writable_events", recreates kafka+MV as a `_temp` pair (remediation).
- 23:52 revert #61041 merged (code only — does NOT restore the live MV/schema).
- 02:29 status page marked resolved. **Top-level columns still 0%.**

## Root cause (mechanism)

1. Top-level cols on `sharded_events` are `DEFAULT replaceRegexpAll(JSONExtractRaw(properties,'$x'),…)`.
   A `DEFAULT` expr runs **only when the INSERT omits the column**.
2. `writable_events` (Distributed → sharded*events) carries `$session_id`/`$window_id`/`$group*\*`as
**bare`String`, no default\*\* (long-standing; query_log shows no DDL touched them in 18h).
3. Therefore the value is only correct **when the MV explicitly projects it**. The pre-incident MV did.
4. The `dmat` drop+recreate replaced the US MV with one that **does not project** these 7 columns.
   → MV omits them → `writable_events` fills `''` → Distributed ships `''` to `sharded_events`
   → `''` is an explicit value → `DEFAULT` is bypassed → stored empty.

## Why the revert (#61041) didn't fix it

Reverting deletes migration 0267 from the codebase; it does **not** drop/recreate the live ClickHouse
objects. The non-projecting US MV (+ `_temp` pair) is still live. A **forward fix** is required.

## Fix path (for the morning)

**Forward fix (restore new-event population) — rebuild the MV to match EU:**
Recreate the US events MV(s) so they project the 7 columns again (compute from `properties`), i.e. make
US's `events_json_mv_ws` match EU's `events_json_ws_mv` SELECT. Resolve the `events_json_mv_ws_temp` /
`kafka_events_json_ws_temp` swap state at the same time (confirm which kafka table is actually consuming —
the non-temp `events_json_mv_ws` currently reads from `kafka_events_json_ws`, which no longer exists).
Alternative (simpler, riskier): drop the 7 bare columns from `writable_events` so inserts omit them and
the `sharded_events` DEFAULT fires; or add matching DEFAULT exprs to those `writable_events` columns.

**Backfill the gap (22:15 UTC → fix time):** rows already ingested have empty top-level values permanently
until repopulated. Reliable path is a mutation per column, scoped to affected partitions:
`ALTER TABLE sharded_events UPDATE \`$session_id\` = replaceRegexpAll(JSONExtractRaw(properties,'$session_id'), …)
WHERE \`$session_id\` = '' AND <partition filter>` (repeat for the 7 cols).
`MATERIALIZE COLUMN` may not overwrite existing non-empty/`''` parts depending on CH version — verify before
relying on it. Until backfilled, queries can fall back to `JSONExtractString(properties,'$session_id')`.

Owner: #team-ingestion. Breaking PR author: Sandy Spicer. Incident lead: Bryan Ciaraldi.
Heavily involved: Paweł Szczur, James Greenhill, Rory Shanks, Tommy Gilmore, Tom Piccirello.

---

## Detection queries (copy-paste; re-run in the morning)

### 1. Is it still broken? (data tier, US online = db 143)

```bash
cd ~/code/posthog && ./bin/hogli metabase:query --region us --database-id 143 <<'SQL'
SELECT
  count() AS total,
  round(100*countIf(`$session_id`!='')/count(),3)              AS pct_session_id,
  round(100*countIf(`$window_id`!='')/count(),3)               AS pct_window_id,
  round(100*countIf(`$group_0`!='')/count(),3)                 AS pct_group_0,
  round(100*countIf(`$session_id_uuid` IS NOT NULL)/count(),3) AS pct_sid_uuid_MATERIALIZED,
  round(100*countIf(JSONExtractString(properties,'$session_id')!='')/count(),3) AS pct_props_session_id
FROM events
WHERE _timestamp > now() - INTERVAL 15 MINUTE
SQL
```

- **Broken:** `pct_session_id = 0` while `pct_props_session_id > 0`.
- **Recovered:** `pct_session_id` tracks `pct_props_session_id` (and `pct_sid_uuid`, which never broke).

### 2. Root-cause check — does the live US MV project the columns? (ingestion = db 140)

```bash
cd ~/code/posthog && ./bin/hogli metabase:query --region us --database-id 140 <<'SQL'
WITH (SELECT create_table_query FROM system.tables WHERE database='posthog' AND name='events_json_mv_ws') AS mv
SELECT
  position(mv,'$session_id')>0 AS projects_session_id,
  position(mv,'$window_id')>0  AS projects_window_id,
  position(mv,'$group_0')>0    AS projects_group_0
SQL
```

- **Broken:** all `0`. **Fixed:** all `1`. (EU's `events_json_ws_mv` on `--region eu --database-id 100` returns `1`s — the control.)

### 3. writable_events column shape (should be bare while broken; db 140)

```bash
cd ~/code/posthog && ./bin/hogli metabase:query --region us --database-id 140 <<'SQL'
SELECT name, default_kind, default_expression
FROM system.columns
WHERE database='posthog' AND table='writable_events' AND startsWith(name,'$')
ORDER BY name
SQL
```

### 4. Onset / recovery time-series (db 143)

```bash
cd ~/code/posthog && ./bin/hogli metabase:query --region us --database-id 143 <<'SQL'
SELECT toStartOfFifteenMinutes(_timestamp) AS bucket, count() AS total,
       round(100*countIf(`$session_id`!='')/count(),2) AS pct_toplevel,
       round(100*countIf(JSONExtractString(properties,'$session_id')!='')/count(),2) AS pct_props
FROM events
WHERE _timestamp > now() - INTERVAL 8 HOUR AND team_id = 2
GROUP BY bucket ORDER BY bucket
SQL
```

## Key references

- Breaking: PR #59681 `6554d68409a` + migration `0267_wire_up_existing_dmat_string_columns.py`
- Follow-up: PR #61036 (`ca854377d50`, writable_events on DATA), revert PR #61041 (`0e623c2982d`)
- Incident #880: channel `C0B7MKC1MCZ`
- MV definition in code: `posthog/models/event/sql.py` (`EVENTS_TABLE_JSON_MV_SQL`, `EVENTS_TABLE_BASE_SQL`)
