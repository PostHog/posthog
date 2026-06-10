"""
Detection of whether a team has begun ingesting real production traffic.

This is the activation milestone behind `Team.ingested_production_event`. The
file is split into two layers so the heuristic can be retuned without
touching the rest of the system:

  1. CRITERION  — `_teams_meeting_criterion(team_ids)` is the single source
                  of truth for what counts as "production traffic". The
                  contract is intentionally narrow: `Iterable[team_id] ->
                  dict[team_id, ProductionTrafficSignal]`. The implementation
                  is free to change.

  2. TRANSITION — `_mark_teams_ingested_production_event(signals, now)` is
                  the only code that marks the column and emits the
                  `first team production event ingested` analytics event.
                  Idempotent under concurrent runs via `SELECT FOR UPDATE
                  SKIP LOCKED`.

Scheduling lives in `products/growth/dags/team_production_event_activation.py`,
which wires these helpers into a Dagster job + daily schedule.

A team qualifies on the strongest available signal for its SDK class, checked
in this order within the window:

  - WEB:    at least one event whose origin host (`$host`, falling back to the
            host of `$current_url`) is a real public host — see
            `is_production_host`. `$ip`/GeoIP can't be used instead: a
            developer's local backend still reaches us over the public
            internet from a public IP.
  - MOBILE: enough distinct physical devices on events that affirm
            `$is_emulator: false`. A single non-emulator event is *not*
            production evidence — a developer testing on their own phone looks
            identical — but several distinct physical devices means the app
            shipped to real hands.
  - SERVER: enough distinct users on events from server-side SDKs. There is no
            environment signal at all in backend events, so this is a pure
            diversity proxy and intentionally has the highest bar.

Detection is fail-closed: each leg requires its positive signal, and anything
local/private/reserved/ambiguous does not qualify. A false positive silently
corrupts the activation metric and is hard to detect; a false negative is
recoverable — the daily sweep re-checks unflagged teams.
"""

from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from datetime import datetime
from ipaddress import IPv4Address, IPv6Address, ip_address
from typing import Final, Literal

from django.db import transaction

from posthog.clickhouse.client import sync_execute
from posthog.clickhouse.query_tagging import Feature, Product, tags_context
from posthog.event_usage import groups
from posthog.models.team.team import Team
from posthog.ph_client import ph_scoped_capture

# --- Heuristic parameters ---------------------------------------------------
# Tune these to recalibrate the metric.

WINDOW_DAYS: Final[int] = 30
SWEEP_BATCH_SIZE: Final[int] = 5_000

# Cap on distinct hosts fetched per team. Bounds the result set when a team
# emits pathological host cardinality; a production host pushed past the cap
# is only a transient false negative — the next daily run resamples.
HOSTS_PER_TEAM_CAP: Final[int] = 1_000

# MOBILE: distinct physical devices (`$device_id`, falling back to
# `distinct_id`) on `$is_emulator: false` events. One developer owns one or
# two test phones; this many distinct real devices means the app shipped.
# Device IDs are stabler than anonymous distinct_ids against one developer's
# login/logout/reinstall churn.
MOBILE_PHYSICAL_DEVICES_THRESHOLD: Final[int] = 3

# SERVER: distinct users on events from server-side SDKs. Backend events carry
# no environment signal whatsoever, so this is a diversity proxy: a production
# backend serves many distinct users, a developer's test run uses a handful of
# fixture IDs. Deliberately the highest bar of the three legs — a seeded dev
# database can fabricate distinct IDs cheaply.
SERVER_LIB_USERS_THRESHOLD: Final[int] = 10

# `$lib` values treated as server-side evidence. Deliberately a positive
# allowlist (not "anything without a host") so that web traffic with stripped
# properties or e2e suites hammering localhost with fresh anonymous IDs can't
# drift into this leg.
SERVER_SIDE_LIBS: Final[tuple[str, ...]] = (
    "posthog-python",
    "posthog-node",
    "posthog-php",
    "posthog-ruby",
    "posthog-go",
    "posthog-java",
    "posthog-dotnet",
    "posthog-elixir",
    "posthog-rs",
)


@dataclass(frozen=True, kw_only=True)
class ProductionTrafficSignal:
    """Which signal qualified a team, for the emitted analytics event.

    `production_host` is set for the web leg; `distinct_count` carries the
    device count (mobile leg) or user count (server leg).
    """

    kind: Literal["production_host", "mobile_physical_devices", "server_lib_users"]
    production_host: str | None = None
    distinct_count: int | None = None


# Reserved / non-public TLD suffixes. A host ending in one of these is a dev or
# internal name, never a real public environment. Matched as an exact suffix
# (with the leading dot) so that production hosts which merely *contain* one of
# these words — mylocalbiz.com, localhosting.com — are not caught.
RESERVED_TLD_SUFFIXES: Final[tuple[str, ...]] = (
    ".local",
    ".test",
    ".internal",
    ".invalid",
    ".example",
    ".localdomain",
    ".home.arpa",
)


# --- Criterion --------------------------------------------------------------


def is_production_host(raw_host: str) -> bool:
    """Decide whether an event origin host points at a real, public production
    environment — as opposed to a developer's localhost/dev setup.

    Fail-closed: returns True only on a positive public-host signal. IP
    literals classify by address range via `ipaddress` (`is_global`), which is
    stricter than plain RFC 1918: CGNAT (100.64/10, e.g. Tailscale),
    documentation and benchmarking ranges all stay non-production. IPv4-mapped
    IPv6 literals classify by the embedded IPv4 address.
    """
    host = _strip_port_and_brackets(raw_host.strip().lower())
    if not host:
        return False
    if host == "localhost" or host.endswith(".localhost"):
        return False
    if host.endswith(RESERVED_TLD_SUFFIXES):
        return False

    try:
        ip: IPv4Address | IPv6Address = ip_address(host)
    except ValueError:
        if ":" in host:
            return False  # colon-y but not a valid IPv6 literal — garbage
        if "." not in host:
            return False  # bare machine name like "my-laptop"
        if all(label.isdigit() for label in host.split(".")):
            return False  # malformed IP literal like 256.1.1.1 — never a navigable host
        return True  # a dotted host that's neither reserved nor an IP — a real public domain

    if isinstance(ip, IPv6Address) and ip.ipv4_mapped is not None:
        ip = ip.ipv4_mapped
    return ip.is_global


# `$host` carries a port (localhost:3000, [::1]:3000). Strip brackets and the
# port so we classify the bare host. A bare IPv6 literal (>=2 colons,
# unbracketed) has no port to strip — only bracketed IPv6 can carry one.
def _strip_port_and_brackets(host: str) -> str:
    if host.startswith("["):
        closing_bracket = host.find("]")
        return host[1:closing_bracket] if closing_bracket != -1 else host[1:]

    colon_count = host.count(":")
    if colon_count >= 2:
        return host
    if colon_count == 1:
        return host.partition(":")[0]
    return host


def _teams_meeting_criterion(team_ids: Iterable[int]) -> dict[int, ProductionTrafficSignal]:
    """Return `{team_id: signal}` for the subset of `team_ids` whose recent
    traffic meets the criterion, with the strongest signal that matched (web
    origin host > mobile physical devices > server-side user diversity).

    Single source of truth for "what counts as production traffic." ClickHouse
    only collects per-team evidence — candidate origin hosts (`$host`, falling
    back to the host of `$current_url`), physical-device counts, and
    server-side user counts; host classification happens in
    `is_production_host` so it stays unit-testable. The exact-localhost
    prefilter in SQL is an optimization only (it keeps the dominant dev noise
    out of the result set and away from the per-team cap); correctness lives
    in the Python classifier. `$is_emulator` is matched against its raw JSON
    value so both boolean and stringly-typed `false` count, and anything else
    (true, absent, garbage, SDK versions that don't send it) fails closed.
    """
    team_id_list = list(team_ids)
    if not team_id_list:
        return {}

    # Internal background job, not a customer-facing query — tag it so it's
    # attributed to growth in ClickHouse query analytics (and so it doesn't trip
    # the untagged-query guard that raises in local dev).
    with tags_context(product=Product.GROWTH, feature=Feature.ENRICHMENT):
        rows = sync_execute(
            """
            SELECT
                team_id,
                groupUniqArrayIf(%(hosts_per_team_cap)s)(
                    host,
                    host != '' AND host != 'localhost' AND NOT startsWith(host, 'localhost:')
                ) AS candidate_hosts,
                uniqIf(
                    if(device_id != '', device_id, distinct_id),
                    is_emulator_raw IN ('false', '"false"')
                ) AS physical_devices,
                uniqIf(distinct_id, lib IN %(server_side_libs)s) AS server_lib_users
            FROM (
                SELECT
                    team_id,
                    distinct_id,
                    if(
                        JSONExtractString(properties, '$host') != '',
                        JSONExtractString(properties, '$host'),
                        domain(JSONExtractString(properties, '$current_url'))
                    ) AS host,
                    JSONExtractRaw(properties, '$is_emulator') AS is_emulator_raw,
                    JSONExtractString(properties, '$device_id') AS device_id,
                    JSONExtractString(properties, '$lib') AS lib
                FROM events
                WHERE team_id IN %(team_ids)s
                  AND timestamp >= now() - toIntervalDay(%(window_days)s)
            )
            GROUP BY team_id
            HAVING notEmpty(candidate_hosts)
                OR physical_devices >= %(mobile_threshold)s
                OR server_lib_users >= %(server_threshold)s
            """,
            {
                "team_ids": team_id_list,
                "window_days": WINDOW_DAYS,
                "hosts_per_team_cap": HOSTS_PER_TEAM_CAP,
                "server_side_libs": list(SERVER_SIDE_LIBS),
                "mobile_threshold": MOBILE_PHYSICAL_DEVICES_THRESHOLD,
                "server_threshold": SERVER_LIB_USERS_THRESHOLD,
            },
        )

    qualifying: dict[int, ProductionTrafficSignal] = {}
    for team_id, candidate_hosts, physical_devices, server_lib_users in rows:
        production_host = next((host for host in candidate_hosts if is_production_host(host)), None)
        if production_host is not None:
            qualifying[team_id] = ProductionTrafficSignal(kind="production_host", production_host=production_host)
        elif physical_devices >= MOBILE_PHYSICAL_DEVICES_THRESHOLD:
            qualifying[team_id] = ProductionTrafficSignal(
                kind="mobile_physical_devices", distinct_count=physical_devices
            )
        elif server_lib_users >= SERVER_LIB_USERS_THRESHOLD:
            qualifying[team_id] = ProductionTrafficSignal(kind="server_lib_users", distinct_count=server_lib_users)
    return qualifying


# --- Transition -------------------------------------------------------------


def _mark_teams_ingested_production_event(team_signals: Mapping[int, ProductionTrafficSignal], now: datetime) -> int:
    """Mark `ingested_production_event` for the given teams and emit one
    activation event per team that is newly marked.

    Concurrent-safe via `SELECT FOR UPDATE SKIP LOCKED`: a second run
    running in parallel sees only the rows the first run hasn't locked, so
    each team's event fires at most once. Returns the number of teams that
    were marked this call.
    """
    if not team_signals:
        return 0

    with transaction.atomic():
        teams_to_mark = list(
            Team.objects.select_for_update(skip_locked=True)
            .filter(id__in=list(team_signals.keys()), ingested_production_event=False)
            .only("id", "uuid")
        )
        if not teams_to_mark:
            return 0
        Team.objects.filter(id__in=[t.id for t in teams_to_mark]).update(
            ingested_production_event=True,
            ingested_production_event_last_checked_at=now,
        )

    # Emit outside the transaction so the PostHog client round-trip doesn't
    # hold row locks. Lost events on worker exit are guarded by
    # `ph_scoped_capture`'s explicit flush.
    with ph_scoped_capture() as capture:
        for team in teams_to_mark:
            signal = team_signals[team.id]
            properties = {
                "detection_signal": signal.kind,
                "production_host": signal.production_host,
                "distinct_count": signal.distinct_count,
                "window_days": WINDOW_DAYS,
            }
            capture(
                distinct_id=str(team.uuid),
                event="first team production event ingested",
                properties={key: value for key, value in properties.items() if value is not None},
                groups=groups(team=team),
            )
    return len(teams_to_mark)


# --- Per-batch helper used by the Dagster job ------------------------------


def evaluate_and_mark_team_batch(team_ids: Iterable[int], now: datetime) -> tuple[int, int]:
    """Evaluate one batch of unflagged team IDs and apply the result.

    Returns `(qualifying_count, marked_count)`. `marked_count <=
    qualifying_count` because a concurrent run may have already marked
    rows under `SELECT FOR UPDATE SKIP LOCKED`.
    """
    batch = list(team_ids)
    if not batch:
        return 0, 0

    qualifying_signals = _teams_meeting_criterion(batch)
    marked = _mark_teams_ingested_production_event(qualifying_signals, now=now) if qualifying_signals else 0

    # Bump `_last_checked_at` for the rest so we know we evaluated them.
    # Qualifying teams already had `_last_checked_at` set inside the
    # transition helper, so don't double-write them here.
    non_qualifying = [tid for tid in batch if tid not in qualifying_signals]
    if non_qualifying:
        Team.objects.filter(id__in=non_qualifying).update(
            ingested_production_event_last_checked_at=now,
        )

    return len(qualifying_signals), marked
