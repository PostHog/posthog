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
  - MOBILE: enough distinct physical devices (`$device_id`) on events that
            affirm `$is_emulator: false`. A single non-emulator event is *not*
            production evidence — a developer testing on their own phone looks
            identical — but several distinct physical devices means the app
            shipped to real hands. Events without a `$device_id` fail closed:
            distinct_ids churn under login/logout/reinstall, so they can't
            stand in for devices.
  - SERVER: enough distinct users on events from server-side SDKs. There is no
            environment signal at all in backend events, so this is a pure
            diversity proxy and intentionally has the highest bar.

Detection is fail-closed: each leg requires its positive signal, and anything
local/private/reserved/ambiguous does not qualify. A false positive silently
corrupts the activation metric and is hard to detect; a false negative is
recoverable while the team keeps sending production traffic — the sweep
re-checks unflagged teams. One segment is permanently invisible by design:
teams whose only traffic is posthog-js from non-public origins (Electron /
Capacitor wrapper apps report localhost-style hosts; intranet or VPN-only
deployments report private ones) can never satisfy any leg.
"""

from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from datetime import datetime, timedelta
from ipaddress import IPv4Address, IPv6Address, ip_address
from typing import Final, Literal

from django.db import transaction

import structlog

from posthog.clickhouse.client import sync_execute
from posthog.clickhouse.client.connection import Workload
from posthog.clickhouse.query_tagging import Feature, Product, tags_context
from posthog.cloud_utils import is_cloud
from posthog.event_usage import groups
from posthog.exceptions_capture import capture_exception
from posthog.models.event.sql import EVENTS_QUERY_TABLE
from posthog.models.property.util import get_property_string_expr
from posthog.models.team.team import Team
from posthog.ph_client import ph_scoped_capture

logger = structlog.get_logger(__name__)

# --- Heuristic parameters ---------------------------------------------------
# Tune these to recalibrate the metric.

WINDOW_DAYS: Final[int] = 30
SWEEP_BATCH_SIZE: Final[int] = 5_000

# How long after an evaluation a still-unflagged team is left alone before the
# sweep re-checks it. Production events stay detectable for WINDOW_DAYS, so a
# backoff well below the window cannot miss a team that keeps sending traffic —
# it only defers detection by at most the backoff. This is what keeps both the
# ClickHouse scan volume and the `posthog_team` write churn bounded as the
# population of never-qualifying teams grows.
RECHECK_BACKOFF: Final[timedelta] = timedelta(days=7)

# Cap on distinct hosts fetched per team, bounding result size and aggregation
# state when a team emits pathological host cardinality. Retention under the
# cap is NOT a random resample: a production host crowded out by >1k distinct
# noise hosts can stay crowded out on later runs too. The SQL prefilter on the
# dominant dev noise (localhost/loopback, which also covers port-churn) is what
# keeps real production hosts inside the cap in practice.
HOSTS_PER_TEAM_CAP: Final[int] = 1_000

# Hostnames are capped at 253 characters by RFC 1035; anything longer is
# crafted input and fails closed. The SQL-side substring cap (256) bounds
# aggregation memory against unbounded user-controlled `$host` values.
MAX_HOSTNAME_LENGTH: Final[int] = 253
SQL_HOST_LENGTH_CAP: Final[int] = 256

# MOBILE: distinct physical devices (`$device_id`) on `$is_emulator: false`
# events. One developer owns one or two test phones; this many distinct real
# devices means the app shipped. Device IDs are required (no distinct_id
# fallback) because anonymous distinct_ids churn under one developer's
# login/logout/reinstall cycles.
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

# Well-known dev-tunnel and wildcard-DNS suffixes. These are public hosts that
# overwhelmingly serve a developer's local machine (ngrok/cloudflared tunnels,
# nip.io-style wildcard DNS resolving to an embedded IP, tailnet-only hosts),
# so they don't count as production. Preview-deploy platforms (e.g.
# *.vercel.app) are deliberately NOT listed — real production apps live there.
DEV_TUNNEL_SUFFIXES: Final[tuple[str, ...]] = (
    ".ngrok.io",
    ".ngrok-free.app",
    ".ngrok.app",
    ".trycloudflare.com",
    ".loca.lt",
    ".serveo.net",
    ".nip.io",
    ".sslip.io",
    ".xip.io",
    ".localtest.me",
    ".lvh.me",
    ".ts.net",
)


# --- Criterion --------------------------------------------------------------


def is_production_host(raw_host: str) -> bool:
    """Decide whether an event origin host points at a real, public production
    environment — as opposed to a developer's localhost/dev setup.

    Fail-closed: returns True only on a positive public-host signal. IP
    literals classify by address range via `ipaddress` (`is_global`), which is
    stricter than plain RFC 1918: CGNAT (100.64/10, e.g. Tailscale),
    documentation and benchmarking ranges all stay non-production. IPv4-mapped
    IPv6 literals classify by the embedded IPv4 address. Trailing dots are
    stripped before matching — browsers report `location.host` as `localhost.`
    for `http://localhost./`, and an FQDN trailing dot must not defeat the
    localhost/suffix/IP checks.
    """
    host = _strip_port_and_brackets(raw_host.strip().lower()).rstrip(".")
    if not host or len(host) > MAX_HOSTNAME_LENGTH:
        return False
    if host == "localhost" or host.endswith(".localhost"):
        return False
    if host.endswith(RESERVED_TLD_SUFFIXES):
        return False
    if host.endswith(DEV_TUNNEL_SUFFIXES):
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
    `is_production_host` so it stays unit-testable. The localhost/loopback
    prefilter in SQL is an optimization only (it keeps the dominant dev noise
    out of the result set and away from the per-team cap); correctness lives
    in the Python classifier. `$is_emulator` is matched against its raw JSON
    value so both boolean and stringly-typed `false` count, and anything else
    (true, absent, garbage, SDK versions that don't send it) fails closed.
    """
    team_id_list = list(team_ids)
    if not team_id_list:
        return {}

    # Use materialized property columns where the deployment has them; the
    # fallback is the JSONExtractString these expressions would otherwise be.
    # `$is_emulator` stays on JSONExtractRaw deliberately: JSONExtractString
    # returns '' for JSON booleans, so the string-expression fallback would
    # silently kill the mobile leg on deployments without the materialized
    # column, while the raw value works everywhere.
    host_expr, _ = get_property_string_expr("events", "$host", "'$host'", "properties")
    current_url_expr, _ = get_property_string_expr("events", "$current_url", "'$current_url'", "properties")
    device_id_expr, _ = get_property_string_expr("events", "$device_id", "'$device_id'", "properties")
    lib_expr, _ = get_property_string_expr("events", "$lib", "'$lib'", "properties")
    properties_expr = "toJSONString(properties)" if EVENTS_QUERY_TABLE() == "events_json" else "properties"

    # Internal background job, not a customer-facing query — tag it so it's
    # attributed to growth in ClickHouse query analytics (and so it doesn't trip
    # the untagged-query guard that raises in local dev). Routed to the offline
    # cluster on cloud: this is a fleet sweep over raw events and must not
    # compete with customer-facing queries.
    workload = Workload.OFFLINE if is_cloud() else Workload.DEFAULT
    # The interpolated fragments are server-side SQL expressions from
    # get_property_string_expr, never user input; all values go through
    # query parameters.
    query = f"""
        SELECT
            team_id,
            groupUniqArrayIf(%(hosts_per_team_cap)s)(
                host,
                host != ''
                AND host != 'localhost'
                AND NOT startsWith(host, 'localhost:')
                AND NOT startsWith(host, '127.0.0.1')
            ) AS candidate_hosts,
            uniqIf(
                device_id,
                device_id != '' AND is_emulator_raw IN ('false', '"false"')
            ) AS physical_devices,
            uniqIf(distinct_id, lib IN %(server_side_libs)s) AS server_lib_users
        FROM (
            SELECT
                team_id,
                distinct_id,
                substring(
                    if({host_expr} != '', {host_expr}, domain({current_url_expr})),
                    1,
                    %(host_length_cap)s
                ) AS host,
                JSONExtractRaw({properties_expr}, '$is_emulator') AS is_emulator_raw,
                {device_id_expr} AS device_id,
                {lib_expr} AS lib
            FROM {EVENTS_QUERY_TABLE()}
            WHERE team_id IN %(team_ids)s
              AND timestamp >= now() - toIntervalDay(%(window_days)s)
        )
        GROUP BY team_id
        HAVING notEmpty(candidate_hosts)
            OR physical_devices >= %(mobile_threshold)s
            OR server_lib_users >= %(server_threshold)s
    """
    with tags_context(product=Product.GROWTH, feature=Feature.ENRICHMENT):
        rows = sync_execute(
            query,
            {
                "team_ids": team_id_list,
                "window_days": WINDOW_DAYS,
                "hosts_per_team_cap": HOSTS_PER_TEAM_CAP,
                "host_length_cap": SQL_HOST_LENGTH_CAP,
                "server_side_libs": list(SERVER_SIDE_LIBS),
                "mobile_threshold": MOBILE_PHYSICAL_DEVICES_THRESHOLD,
                "server_threshold": SERVER_LIB_USERS_THRESHOLD,
            },
            workload=workload,
            # One pathological batch must time out rather than occupy the pool
            # and shard CPU indefinitely; the op's retry policy contains the
            # failure to that batch.
            settings={"max_execution_time": 600},
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
            # `groups()` below reads organization_id — fetch it here so the
            # emit loop stays free of per-team lazy-load queries.
            .only("id", "uuid", "organization_id")
        )
        if not teams_to_mark:
            return 0
        Team.objects.filter(id__in=[t.id for t in teams_to_mark]).update(
            ingested_production_event=True,
            ingested_production_event_last_checked_at=now,
        )

    # Audit trail: the signal kind only otherwise exists in the emitted
    # analytics events, which are at-most-once — log it so a bad run can be
    # scoped and repaired from worker logs.
    marked_kinds = {team.id: team_signals[team.id].kind for team in teams_to_mark}
    for start in range(0, len(teams_to_mark), 500):
        chunk = teams_to_mark[start : start + 500]
        logger.info(
            "marked_teams_ingested_production_event",
            team_signals={team.id: marked_kinds[team.id] for team in chunk},
        )

    # Emit outside the transaction so the PostHog client round-trip doesn't
    # hold row locks. Emission is at-most-once: rows are already marked, so a
    # crash between the commit above and the flush loses those events for good
    # (re-runs filter on ingested_production_event=False). The column is the
    # source of truth; the per-team guard below keeps one bad team from
    # forfeiting the rest of the batch.
    with ph_scoped_capture() as capture:
        for team in teams_to_mark:
            signal = team_signals[team.id]
            properties = {
                "detection_signal": signal.kind,
                "production_host": signal.production_host,
                "distinct_count": signal.distinct_count,
                "window_days": WINDOW_DAYS,
                # Parity with nodejs captureTeamEvent, which stamps the team
                # uuid on team-scoped events.
                "team": str(team.uuid),
            }
            try:
                capture(
                    distinct_id=str(team.uuid),
                    event="first team production event ingested",
                    properties={key: value for key, value in properties.items() if value is not None},
                    groups=groups(team=team),
                )
            except Exception as e:
                capture_exception(e, {"team": "team-growth", "team_id": team.id})
                logger.exception("production_event_activation_capture_failed", team_id=team.id)
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

    # Stamp `_last_checked_at` for the rest — the candidate query uses it to
    # skip recently-checked teams (RECHECK_BACKOFF), so this write is what
    # keeps the sweep's recurring cost bounded. Qualifying teams already had
    # it set inside the transition helper, so don't double-write them here.
    non_qualifying = [tid for tid in batch if tid not in qualifying_signals]
    if non_qualifying:
        Team.objects.filter(id__in=non_qualifying).update(
            ingested_production_event_last_checked_at=now,
        )

    return len(qualifying_signals), marked
