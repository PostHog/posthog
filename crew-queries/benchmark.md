# Sessionless web analytics shape: benchmark

Data for the query-shape experiment behind the `webAnalyticsSessionlessShape` modifier. Not a
recommendation. It covers the sessionless shape, shard-local aggregation as its execution strategy,
and a narrow path cube. Absolute timings, row counts and result values stay out of the repo; this
file states every outcome relative to today's paths.

## What ran

- Two production teams: PostHog's own project (team 2, US) and a large EU team. Both regions run the
  same ClickHouse version.
- Ranges of 7, 30 and 90 days ending on the same UTC day.
- Every query is the SQL the HogQL printer emits for the runner, with `useNewEventsSchema=true` so
  events come from `events_json`, filled per team and range, run read-only through Metabase by
  `run_bench.sh`, and read back from `system.query_log` by its `log_comment` (`query_log_stats.sql`).
  Time, rows read and peak memory are ClickHouse's own numbers for the initial query; they include
  the remote shards' reads, not Metabase overhead.
- Paths compared:
  - `sessionless`: this branch's shape. One scan of every event with a UUIDv7 `$session_id`, grouped
    by session; visitors from the raw `person_id` column (no overrides join).
  - `sessionless_pv`: the same, with the per-session scan limited to `$pageview`/`$screen` events.
    Benchmark-only variant; bounce cannot see autocapture and duration only spans pageviews.
  - `no_join`: today's two-scan path for unfiltered queries (events side plus a sessions-table side,
    no join), sessions v3. `join`: the legacy events JOIN sessions path, sessions v3.
  - `no_join_v2` / `join_v2`: the same two paths against the sessions v2 tables, which is what the
    app's default `sessionTableVersion=auto` resolves to.
  - `dimensional`: a read of `web_stats_dimensional_preaggregated` and
    `web_bounces_dimensional_preaggregated`, filtered to the job with the latest `computed_at` per
    UTC day. The app takes the ready job ids from Postgres instead; the row set is the same when the
    latest job is the ready one.
- Breakdowns run with `LIMIT 100`, no path cleaning, bounce rate on for pages and entry page, off for
  exit page. The overview has no compare period.
- Channel type is not in scope of the shape: `channel_definition_dict` does not exist on the events
  cluster, so the sessionless shape serves overview, pages, entry page and exit page only, and the
  channel breakdown keeps its current paths. Nothing here reads a dictionary.

## Caveats

- One run per query, warm-ish caches (the same 7d scan runs several times across paths). Treat
  times as order-of-magnitude, rows read and memory as exact.
- The sessionless shape sees only in-range events of a session; the sessions table sees the whole
  session (bounded to 31 days around its id timestamp). Duration and entry/exit page differ at the
  range edges by construction.
- `events_json` is sharded by `sipHash64(distinct_id)`; a session that identifies mid-way sits on two
  shards. Q2 measures the share.

## Headline outcomes

| Question                                        | Team 2 (US)                                                                      | Large EU team                                                       |
| ----------------------------------------------- | -------------------------------------------------------------------------------- | ------------------------------------------------------------------- |
| rows read, sessionless vs today's two-scan path | ~30x more at every range                                                         | ~3-6x more                                                          |
| time, sessionless vs today's two-scan path      | within 2x either way at 7/30/90d                                                 | ~2.5x faster at 7d; today's path runs out of memory at 30d and 90d  |
| peak memory, sessionless vs today's two-scan    | 10-60x more; grows with sessions in range                                        | ~2x more at 7d; both exceed the memory limit at 90d for breakdowns  |
| time, sessionless vs legacy join                | 4-15x faster                                                                     | 4-15x faster                                                        |
| sessions whose events sit on >1 shard (7d)      | a few percent, almost all with >1 `distinct_id`                                  | about 1%, same pattern                                              |
| visitors from raw `person_id` vs overrides join | +19% at 7d, +6% at 30d                                                           | +1% at 7d, +0.2% at 30d                                             |
| overrides join cost                             | a fraction of a second over the pageview scan                                    | same                                                                |
| per-shard aggregation, overview                 | memory down 2-3 orders of magnitude, time halves; sessions +5%, visitors -1..-9% | memory down ~30x, time halves; sessions +0.5%, visitors within 1%   |
| pageview-only variant                           | reads 6-100x fewer rows; bounce rate doubles (cannot see autocapture)            | same                                                                |
| lazy paths cube, unfiltered pages               | answers in seconds at a few MiB at every range                                   | same; the wide dimensional cube needs GiBs and tens of seconds here |

## What the data says, per question

### Q1: the shape against today's paths and dimensional

- **Reads.** The faithful sessionless shape scans every event of the team, because bounce needs
  autocapture and duration needs the last event. That is 1-2 orders of magnitude more rows than the
  pageview-only scans today's paths run. The events cluster gets through it fast enough that wall
  time stays within 2x of today's path on team 2 at every range.
- **Memory is the problem, not time.** The per-session GROUP BY holds one state per session on the
  coordinator, so peak memory grows with the number of sessions in range and reaches tens of GiB at
  90 days on both teams. The dimensional read stays orders of magnitude smaller on team 2; on the
  large EU team the wide cube is itself big enough that its pages read costs GiBs and tens of
  seconds.
- **Against the two-scan no_join path (what unfiltered queries run today).** On team 2 the two are
  within 2x of each other in time at every range, and no_join reads far fewer rows and uses far less
  memory. On the large EU team no_join_v2 is slower than sessionless at 7d and runs out of memory at
  30d and 90d, where sessionless still answers at 30d. The sessions-cluster side is the limit there.
- **Against the legacy join.** Sessionless is 4-15x faster than the join everywhere it was measured
  and reads nothing from the sessions cluster.
- **Result drift, overview.** Views match to <0.1% (same events). Sessions within +0.5%: a session is
  bucketed by its UUIDv7 timestamp here, by the sessions table's start there. Duration is lower by
  2-13% because the shape only sees in-range events. Bounce rate moves by about one point either
  way.
- **Result drift, breakdowns.** Pages: visitors per page agree to <0.5% where no identify merges
  happen; pages that attract identifies (login, home) run +9-14% because of raw `person_id` (Q4).
  Bounce per entry page differs by -15..+23% relative on team 2 because the entry-page attribution
  differs for a share of sessions (next bullet), and by up to -50% for the root path on the EU team.
- **Entry page on the EU team is a different population.** Sessions v2 stores an empty entry URL
  for roughly one in six of that team's sessions per day although the first pageview in `events_json`
  carries both `$current_url` and `$pathname` for most of them. Those sessions drop out of the entry
  breakdown today; the sessionless shape attributes them, mostly to the root path, which then shows
  far more visitors and views than today's number. The exit breakdown shows the same effect. Which
  population is right is a product question; the v2 ingestion gap is filed as its own issue
  (`diag_entry_pathname.sql` reproduces it).
- **Sessions v3 is not usable as the reference.** On team 2, v3 covers only part of the 90d window
  (the v3 join returns about two thirds of the sessions v2 and sessionless return); on the EU team it
  holds no rows, and the v3 no_join shape fails with `ILLEGAL_TYPE_OF_ARGUMENT` because the EU
  `raw_sessions_v3.pageview_uniq` column is a `uniqExact` state while the HogQL schema merges with
  `uniq`. v2 is what runs for both teams today.
- **The pageview-only variant** reads 6-100x fewer rows and settles the memory question for the
  overview on team 2, but it is wrong on bounce: the rate doubles because it cannot see autocapture.
  It is a valid shape for visitors, views, sessions, entry and exit page, not for bounce or duration.

### Q2: sessions spanning shards

A few percent of team 2 sessions and about 1% of the EU team's sessions have events on more than one
shard (7d). Almost all of them are the sessions with more than one `distinct_id`, which is the
identify case. Per-shard aggregation double-counts exactly these.

### Q3: per-shard aggregation (`distributed_group_by_no_merge = 2` on the per-session subquery, `uniqCombined64`)

- Memory drops by 2-3 orders of magnitude on the overview and time roughly halves. For the pages
  breakdown the counts side still holds a per-path state, so memory barely moves on the EU team and
  the 90d breakdown still fails there.
- Error against the merged shape: sessions +5% on team 2 (the multi-shard sessions counted once per
  shard, plus their split pageview counts), +0.5% on the EU team. Visitors with `uniqCombined64`
  over `any(person_id)` per shard-local session: -1% (7d) to -9% (90d) on team 2, within 1% on the
  EU team. Bounce rate within half a point; duration -4%. Per page the error stays under 1% on
  visitors and views.

### Q4: visitors from `person_id` without the overrides join

- Team 2 (heavy identify use): raw `person_id` overcounts visitors by +19% at 7d and +6% at 30d.
  `uniqExact` confirms the gap is real, not HLL error.
- Large EU team: +1% at 7d, +0.2% at 30d.
- The overrides join itself is cheap here: a fraction of a second and a fraction of the memory of the
  pageview scan on both teams. The accuracy cost is team-dependent and the time saved is small, so
  dropping the join buys little on its own.

### Q5: a narrow (team, day, pathname) aggregate

- Size: the EU team has about 10x the distinct pathnames per day of team 2, and millions on its own.
  A (team, day, pathname) row with `uniq` states for persons and sessions is a few hundred bytes
  before compression, so the narrow cube is roughly an order of magnitude smaller per day than the
  wide dimensional cube for the same team.
- Serving: the existing lazy-precompute paths table (`web_stats_paths_preaggregated`, keyed on team,
  hour window, pathname) answers an unfiltered pages breakdown in single-digit seconds at a few MiB
  on both teams at every range. It only holds the windows people have requested, so its row counts
  are a lower bound and its times are for a partially filled cube. The same query over the wide
  dimensional cube is comparable on team 2 and 1-2 orders of magnitude slower on the EU team.

## Query inventory

- `sql/`: the printed runner shapes (`<overview|pages|entry|exit>__<path>.sql`) with `TEAM_ID`,
  `DATE_FROM` and `DATE_TO` placeholders, as `prepare_and_print_ast` emits them for each runner.
- `run_bench.sh`: runs rendered files through Metabase; `query_log_stats.sql`: reads the runs back;
  `diag_entry_pathname.sql`: the entry-page diagnostic.
- The pageview-only and per-shard variants, the dimensional reads and the Q2/Q4/Q5 queries are
  the `sql/` shapes with the edits each section above describes; the Python that renders and
  summarizes them is not committed, because hoglint has no tier for this directory.
- `rendered/` and `results/` stay out of git (team-specific).
