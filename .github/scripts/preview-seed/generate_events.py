#!/usr/bin/env python3
# ruff: noqa: T201 — standalone CLI payload, print is the output channel
"""Seed a preview box's demo team with synthetic events shaped like prod's
"Product Analytics Quality" dashboard (prod project 2, dashboard 1208527), so
its recreation renders every breakdown tile with the real breakdown values.

TEMPORARY preview-seed payload for the PR #74534 / #74545 comparison — a copy
of the local tmp/generate_synthetic_dashboard_data.py repro script. Runs inside
the box's web image (docker compose run web), writing straight to ClickHouse
and Postgres; preview boxes run no ingestion pipeline.

Weights and latency quantiles were probed from prod on 2026-07-28 (7-day
window). Breakdown VALUES are exact prod values (incl. cross-tile shared
exception messages — the palette-exhaustion repro depends on that overlap);
volumes are scaled down ~3 orders.

Two shapes exist purely for the cross-property color test (values repeated under a
second breakdown property): "query failed" carries QUERY_TYPES names under `kind`,
and client_request_failure carries a `retried` boolean mirroring `cache_hit`. The
matching tiles live at the bottom of dashboard-fixture.json.

Idempotent: wipes previously generated rows (distinct_id 'synth-%') first.
"""

import os
import json
import uuid
import random
from datetime import UTC, datetime, timedelta

import django

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "posthog.settings")
django.setup()

from posthog.local_bootstrap.importer import (  # noqa: E402
    _event_row_to_ch,
    _insert_events_batch,
    _PersonAccumulator,
    _write_persons_to_clickhouse,
    _write_persons_to_postgres,
)
from posthog.models import Team  # noqa: E402

TEAM_ID = int(os.environ.get("SEED_TEAM_ID", "1"))
DAYS = 14
HOST = "us.posthog.com"
rng = random.Random(42)

# ---- probed prod weights -------------------------------------------------

# (query_type, hit_per_day, miss_per_day, (hit p50/p95/p99 ms), (miss p50/p95/p99 ms))
QUERY_TYPES = [
    ("TrendsQuery", 273, 196, (3, 22, 43), (540, 1313, 3103)),
    ("FunnelsQuery", 66, 41, (3, 23, 47), (685, 1918, 3942)),
    ("RetentionQuery", 23, 19, (4, 23, 48), (791, 1894, 3751)),
    ("LifecycleQuery", 8, 6, (3, 21, 40), (665, 1261, 2289)),
    ("PathsQuery", 2, 2, (3, 21, 40), (730, 3394, 8152)),
    ("StickinessQuery", 2, 2, (3, 21, 35), (537, 1433, 4160)),
]

# Context pathnames chosen to hit exactly one tile-group each:
# pa matches ^/project/\d+/insights$ but not icontains /insights/ or /dashboard/.
PATHNAMES = {
    "pa": "/project/2/insights",
    "dash": "/project/2/dashboard/123",
    "ins": "/project/2/insights/abJk29fQ",
}

# (message, events_per_day, person_pool_size) — prod top-12 per context, prod rank order.
EXCEPTIONS = {
    "pa": [
        (
            '[KEA] Can not find path "scenes.dashboard.dashboards.templates.dashboardTemplatesLogic.default-all" in the store.',
            2,
            9,
        ),
        (
            '[KEA] Can not find path "scenes.session-recordings.playlist.sessionRecordingsPlaylistLogic.webAnalytics--" in the store.',
            2,
            8,
        ),
        ("TypeError: Failed to fetch", 3, 5),
        ("AbortError: signal is aborted without reason", 4, 5),
        ("Authentication credentials were not provided.", 2, 4),
        ("kea-listeners breakpoint broke", 1, 3),
        ("Object captured as exception with keys: detail, status", 1, 3),
        (
            '[KEA] Can not find path "scenes.session-recordings.playlist.sessionRecordingsPlaylistLogic.scene---with-search" in the store.',
            1,
            3,
        ),
        ('[KEA] Can not find path "data-warehouse.editor.sqlEditorLogic.default" in the store.', 1, 2),
        ("loadSceneLogViews timed out", 1, 2),
        ("loadRecents timed out", 1, 2),
        ("loadShortcuts timed out", 1, 2),
    ],
    "dash": [
        ("TypeError: Failed to fetch", 30, 45),
        ("Authentication credentials were not provided.", 7, 30),
        (
            '[KEA] Can not find path "scenes.dashboard.dashboards.templates.dashboardTemplatesLogic.default-all" in the store.',
            5,
            24,
        ),
        ("Team ID is not known.", 6, 21),
        ("AbortError: signal is aborted without reason", 26, 14),
        ("Properties Timeline returned no points", 5, 13),
        ("Query {uuid} not found for team {id}", 4, 8),
        ("TypeError: Load failed", 3, 8),
        ("loadRecents timed out", 1, 6),
        ("Object captured as exception with keys: detail, status", 1, 6),
        ("loadSceneLogViews timed out", 1, 6),
        ("Script error.", 4, 5),
    ],
    "ins": [
        ("TypeError: Failed to fetch", 10, 18),
        ("Authentication credentials were not provided.", 3, 9),
        ('[KEA] Can not find path "scenes.dashboard.dashboardLogic.{id}" in the store.', 2, 8),
        ("Properties Timeline returned no points", 2, 7),
        ("Project ID is not known.", 1, 4),
        ("kea-listeners breakpoint broke", 1, 3),
        ("POSTHOG_AI_CONVERSATION_FEEDBACK_CONFIG feature flag is not set", 1, 3),
        ("Team ID is not known.", 1, 2),
        ("Formula references series B, but only 1 series is defined (A)", 1, 2),
        ("A server error occurred.", 1, 2),
        ("TypeError: Load failed", 1, 2),
        ("loadRecents timed out", 1, 2),
    ],
}

# (status, per-day) per API-path context; pathname must (not) contain /dashboard|/insights.
FAILURES = {
    "dashboard": ("/api/projects/2/dashboards/123/", [("404", 26), ("403", 15), ("401", 4), ("500", 1)]),
    "insights": (
        "/api/projects/2/insights/456/",
        [("400", 86), ("403", 42), ("503", 5), ("500", 5), ("404", 3), ("520", 1), ("504", 1), ("502", 1), ("414", 1)],
    ),
    "query_api": (
        "/api/environments/2/query/",
        [
            ("400", 43),
            ("503", 30),
            ("403", 23),
            ("500", 10),
            ("404", 10),
            ("429", 6),
            ("513", 4),
            ("504", 1),
            ("502", 1),
        ],
    ),
}

# (kind, per_day) — repeats QUERY_TYPES values under a second property (`kind`) for the
# cross-property color test; HogQLQuery/EventsQuery appear only here (single-property values).
QUERY_FAILURES = [
    ("TrendsQuery", 18),
    ("HogQLQuery", 11),
    ("FunnelsQuery", 7),
    ("RetentionQuery", 4),
    ("EventsQuery", 3),
]

# (browser, per-day, p50 dropped_frames, p95 dropped_frames)
BROWSERS = [
    ("Chrome", 86, 1, 899),
    ("Safari", 9, 38, 944),
    ("Firefox", 6, 10, 316),
    ("Brave", 5, 0, 164),
    ("Microsoft Edge", 4, 3, 417),
    ("Mobile Safari", 1, 100, 884),
    ("Opera", 1, 0, 267),
    ("Chrome iOS", 1, 67, 435),
]

PAGEVIEWS = {"pa": (60, 40), "dash": (180, 120), "ins": (120, 80)}  # (per-day, pool)
CLICKS = {"pa": (4, 8), "dash": (6, 12), "ins": (5, 9)}  # ($rageclick, $dead_click) per-day
TOASTS = {"dash": 8, "ins": 7}

# ---- person pools ---------------------------------------------------------

persons: dict[str, _PersonAccumulator] = {}
now = datetime.now(UTC)


def make_pool(name: str, size: int) -> list[tuple[str, str]]:
    pool = []
    for i in range(size):
        distinct_id = f"synth-{name}-{i}"
        person_id = str(uuid.uuid5(uuid.NAMESPACE_URL, f"posthog-synth/{name}/{i}"))
        persons[person_id] = _PersonAccumulator(
            properties=json.dumps({"email": f"{distinct_id}@example.com"}),
            version=0,
            created_at=now - timedelta(days=60),
            is_deleted=False,
            distinct_ids={distinct_id: 0},
        )
        pool.append((distinct_id, person_id))
    return pool


# ---- event assembly -------------------------------------------------------

events: list[dict] = []
today = now.replace(hour=0, minute=0, second=0, microsecond=0)


def day_ts(day: int) -> datetime:
    base = today - timedelta(days=DAYS - 1 - day)
    ts = base + timedelta(seconds=rng.randint(6 * 3600, 22 * 3600))
    return min(ts, now - timedelta(minutes=10))


def emit(event: str, day: int, props: dict, pool: list[tuple[str, str]]) -> None:
    distinct_id, person_id = rng.choice(pool)
    events.append(
        {
            "uuid": str(uuid.uuid4()),
            "event": event,
            "properties": json.dumps({"$host": HOST, **props}),
            "timestamp": day_ts(day),
            "distinct_id": distinct_id,
            "person_id": person_id,
        }
    )


def latency(p50: float, p95: float, p99: float) -> float:
    r = rng.random()
    if r < 0.70:
        return rng.uniform(0.4 * p50, 1.6 * p50)
    if r < 0.95:
        return rng.uniform(p50, p95)
    if r < 0.99:
        return rng.uniform(p95, p99)
    return rng.uniform(p99, 1.4 * p99)


backend_pool = make_pool("backend", 20)
exc_pools = {
    (ctx, i): make_pool(f"exc-{ctx}-{i}", size)
    for ctx, msgs in EXCEPTIONS.items()
    for i, (_, _, size) in enumerate(msgs)
}
pv_pools = {ctx: make_pool(f"pv-{ctx}", pool) for ctx, (_, pool) in PAGEVIEWS.items()}
click_pools = {ctx: make_pool(f"click-{ctx}", 10) for ctx in CLICKS}
fail_pool = make_pool("fail", 30)
browser_pools = {
    b: make_pool(f"fr-{b.lower().replace(' ', '-')}", max(3, per_day // 3)) for b, per_day, _, _ in BROWSERS
}

for day in range(DAYS):
    for qt, hits, misses, hit_lat, miss_lat in QUERY_TYPES:
        for count, cache_hit, (p50, p95, p99) in ((hits, True, hit_lat), (misses, False, miss_lat)):
            for _ in range(count):
                emit(
                    "query executed",
                    day,
                    {"query_type": qt, "cache_hit": cache_hit, "response_time_ms": round(latency(p50, p95, p99), 1)},
                    backend_pool,
                )

    for kind, per_day in QUERY_FAILURES:
        for _ in range(per_day):
            emit("query failed", day, {"kind": kind}, backend_pool)

    for ctx, msgs in EXCEPTIONS.items():
        for i, (msg, per_day, _) in enumerate(msgs):
            for _ in range(per_day):
                # $exception_list like real SDK events — the tiles' coalesce() falls through to
                # JSONExtractString, which unescapes quotes; a $exception_message property would
                # keep literal \" in breakdown values (raw-trim extraction).
                emit(
                    "$exception",
                    day,
                    {
                        "$pathname": PATHNAMES[ctx],
                        "$exception_list": [{"type": "Error", "value": msg}],
                        "$exception_values": [msg],
                    },
                    exc_pools[(ctx, i)],
                )

    for ctx, (per_day, _) in PAGEVIEWS.items():
        for _ in range(per_day):
            emit("$pageview", day, {"$pathname": PATHNAMES[ctx]}, pv_pools[ctx])

    for ctx, (rage, dead) in CLICKS.items():
        for _ in range(rage):
            emit("$rageclick", day, {"$pathname": PATHNAMES[ctx]}, click_pools[ctx])
        for _ in range(dead):
            emit("$dead_click", day, {"$pathname": PATHNAMES[ctx]}, click_pools[ctx])

    for ctx, per_day in TOASTS.items():
        for _ in range(per_day):
            emit("toast error", day, {"$pathname": PATHNAMES[ctx]}, click_pools[ctx])

    for _ctx, (api_path, statuses) in FAILURES.items():
        for status, per_day in statuses:
            for _ in range(per_day):
                emit(
                    "client_request_failure",
                    day,
                    {
                        "pathname": api_path,
                        "status": status,
                        # true/false repeat under cache_hit — cross-property boolean color test
                        "retried": rng.random() < 0.25,
                        "$pathname": PATHNAMES["ins"],
                        "$current_url": f"https://{HOST}{PATHNAMES['ins']}",
                    },
                    fail_pool,
                )

    for browser, per_day, p50, p95 in BROWSERS:
        for _ in range(per_day):
            frames = latency(max(p50, 1), p95, 1.1 * p95)
            emit(
                "react_framerate",
                day,
                {"$pathname": PATHNAMES["dash"], "$browser": browser, "dropped_frames": round(min(frames, 10999))},
                browser_pools[browser],
            )

# ---- write ----------------------------------------------------------------

team = Team.objects.get(id=TEAM_ID)
print(f"team {team.id}: inserting {len(persons)} persons, {len(events)} events")

from posthog.clickhouse.client import sync_execute  # noqa: E402
from posthog.local_bootstrap.importer import _ch_tags  # noqa: E402
from posthog.models.event.sql import EVENTS_DATA_TABLE  # noqa: E402
from posthog.persons_db import persons_db_connection  # noqa: E402

with _ch_tags(team.id):
    sync_execute(
        f"ALTER TABLE {EVENTS_DATA_TABLE()} DELETE WHERE team_id = %(team_id)s AND distinct_id LIKE 'synth-%%'",
        {"team_id": team.id},
        settings={"mutations_sync": 1},
    )
print("wiped previous synthetic events")

with persons_db_connection(writer=True, autocommit=True) as conn, conn.cursor() as cursor:
    cursor.execute(
        "SELECT count(*) FROM posthog_person WHERE team_id = %s AND uuid = %s",
        (team.id, next(iter(persons))),
    )
    persons_exist = cursor.fetchone()[0] > 0

if persons_exist:
    print("persons already seeded, skipping")
else:
    _write_persons_to_postgres(team.id, persons)
    _write_persons_to_clickhouse(team, persons)
    print("persons written (postgres + clickhouse)")

insert_now = datetime.now(UTC).replace(tzinfo=None)
rows = [_event_row_to_ch(e, team.id, insert_now) for e in events]
for i in range(0, len(rows), 5000):
    _insert_events_batch(rows[i : i + 5000], team.id)
    print(f"  events {min(i + 5000, len(rows))}/{len(rows)}")

print("done")
