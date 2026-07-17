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
                  SKIP LOCKED`. The emitted event is stamped with the team's
                  conversion time on the web leg (the earliest production-host
                  event in the window, carried on the signal) and the run time
                  otherwise — never the SDK's default send time, so the
                  milestone lands when the team converted, not when the daily
                  sweep noticed.

Scheduling lives in `products/growth/dags/team_production_event_activation.py`,
which wires these helpers into a Dagster job + daily schedule.

A team qualifies on the strongest available signal for its SDK class, checked
in this order within the window:

  - WEB:    at least one event whose origin host (`$host`, falling back to the
            host of `$current_url`) is a real public host — see
            `is_production_host`. `$ip`/GeoIP can't be used instead: a
            developer's local backend still reaches us over the public
            internet from a public IP.
  - MOBILE: enough distinct users (`distinct_id`) on events from mobile SDKs
            (`$lib`), dropping any event flagged `$is_emulator: true`. Mobile
            SDKs don't emit a stable per-device id in event properties, so this
            is a user-diversity proxy like the server leg, not a device count:
            a handful of fixture/dev ids stays below the bar, an app in real
            hands clears it. Emulator-flagged events are dropped so a
            developer's simulator runs don't count; events without the flag are
            kept (most mobile events don't carry it).
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
from dataclasses import dataclass, replace
from datetime import UTC, datetime, timedelta
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
from posthog.models.event.new_events_schema import events_read_table, use_new_events_schema
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

# MOBILE: distinct users (`distinct_id`) on events from mobile SDKs, dropping
# events flagged `$is_emulator: true`. Mobile SDKs don't put a stable per-device
# id in event properties, so this is a user-diversity proxy (like the server
# leg), not a device count. Set above the handful of ids a single developer
# churns through (login/logout/reinstall) so dev traffic stays below the bar.
MOBILE_LIB_USERS_THRESHOLD: Final[int] = 5

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

# `$lib` values treated as mobile-SDK evidence. The mobile leg counts distinct
# users on these libs (excluding emulator-flagged events) — an allowlist, like
# the server leg, so only real mobile SDK traffic feeds the user-diversity proxy.
MOBILE_SIDE_LIBS: Final[tuple[str, ...]] = (
    "posthog-ios",
    "posthog-android",
    "posthog-flutter",
    "posthog-react-native",
)


@dataclass(frozen=True, kw_only=True)
class ProductionTrafficSignal:
    """Which signal qualified a team, for the emitted analytics event.

    `production_host` is set for the web leg; `distinct_count` carries the
    distinct-user count for the mobile and server legs.

    `converted_at` is the team's activation instant: the event timestamp of the
    earliest production-host event in the window. Only the web leg can resolve a
    precise instant cheaply, so it stays None for the mobile/server legs (their
    qualifying moment is a windowed threshold-crossing) and the transition falls
    back to the run time for those.
    """

    kind: Literal["production_host", "mobile_lib_users", "server_lib_users"]
    production_host: str | None = None
    distinct_count: int | None = None
    converted_at: datetime | None = None


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
    origin host > mobile user diversity > server-side user diversity).

    Single source of truth for "what counts as production traffic." ClickHouse
    only collects per-team evidence — candidate origin hosts (`$host`, falling
    back to the host of `$current_url`), mobile-SDK user counts, and
    server-side user counts; host classification happens in
    `is_production_host` so it stays unit-testable. The localhost/loopback
    prefilter in SQL is an optimization only (it keeps the dominant dev noise
    out of the result set and away from the per-team cap); correctness lives
    in the Python classifier.

    Evidence is gathered in two passes so the scan stays under ClickHouse's
    per-query read-bytes limit. The web and server legs and the mobile-user
    upper bound read only the small, materialized-where-available
    `$host`/`$current_url`/`$lib` columns plus `distinct_id` — never the large
    `properties` blob. The mobile leg is the only one that must read
    `properties` (for `$is_emulator`, to drop emulator-flagged events — see
    `_teams_with_mobile_users`), so it runs as a second, narrowly-scoped query
    over only the teams that did NOT qualify on the web leg and that carry
    enough distinct mobile users to possibly cross the threshold. High-volume
    teams overwhelmingly qualify on the web/server legs (or send no mobile-SDK
    `$lib`), so they drop out before the expensive `properties` scan — which is
    what kept a batch of high-traffic teams from blowing the read-bytes limit on
    the old single-query form.
    """
    team_id_list = list(team_ids)
    if not team_id_list:
        return {}

    # Resolved once and threaded through all three evidence queries, so the property fragments
    # below never run against the other schema's table.
    use_new = use_new_events_schema(None)
    events_table = events_read_table(use_new)

    # Use materialized property columns where the deployment has them; the
    # fallback is the JSONExtractString these expressions would otherwise be.
    host_expr, _ = get_property_string_expr("events", "$host", "'$host'", "properties", use_new_events_schema=use_new)
    current_url_expr, _ = get_property_string_expr(
        "events", "$current_url", "'$current_url'", "properties", use_new_events_schema=use_new
    )
    lib_expr, _ = get_property_string_expr("events", "$lib", "'$lib'", "properties", use_new_events_schema=use_new)

    # Internal background job, not a customer-facing query — tag it so it's
    # attributed to growth in ClickHouse query analytics (and so it doesn't trip
    # the untagged-query guard that raises in local dev). Routed to the offline
    # cluster on cloud: this is a fleet sweep over raw events and must not
    # compete with customer-facing queries.
    workload = Workload.OFFLINE if is_cloud() else Workload.DEFAULT

    # Pass 1 — web + server legs and a mobile-user upper bound. Reads only the
    # materialized property columns + distinct_id; the `properties` blob is never
    # touched here. `mobile_candidate_users` is the pre-emulator-filter mobile
    # user count, so a team below the mobile threshold here cannot reach it after
    # the filter and never enters the expensive pass below. The interpolated
    # fragments are server-side SQL expressions from get_property_string_expr,
    # never user input; all values go through query parameters.
    web_server_query = f"""
        SELECT
            team_id,
            groupUniqArrayIf(%(hosts_per_team_cap)s)(
                host,
                host != ''
                AND host != 'localhost'
                AND NOT startsWith(host, 'localhost:')
                AND NOT startsWith(host, '127.0.0.1')
            ) AS candidate_hosts,
            uniqIf(distinct_id, lib IN %(mobile_side_libs)s) AS mobile_candidate_users,
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
                {lib_expr} AS lib
            FROM {events_table}
            WHERE team_id IN %(team_ids)s
              AND timestamp >= now() - toIntervalDay(%(window_days)s)
        )
        GROUP BY team_id
        HAVING notEmpty(candidate_hosts)
            OR mobile_candidate_users >= %(mobile_threshold)s
            OR server_lib_users >= %(server_threshold)s
    """
    with tags_context(product=Product.GROWTH, feature=Feature.ENRICHMENT):
        rows = sync_execute(
            web_server_query,
            {
                "team_ids": team_id_list,
                "window_days": WINDOW_DAYS,
                "hosts_per_team_cap": HOSTS_PER_TEAM_CAP,
                "host_length_cap": SQL_HOST_LENGTH_CAP,
                "mobile_side_libs": list(MOBILE_SIDE_LIBS),
                "server_side_libs": list(SERVER_SIDE_LIBS),
                "mobile_threshold": MOBILE_LIB_USERS_THRESHOLD,
                "server_threshold": SERVER_LIB_USERS_THRESHOLD,
            },
            workload=workload,
            # One pathological batch must time out rather than occupy the pool
            # and shard CPU indefinitely; the op's retry policy contains the
            # failure to that batch.
            settings={"max_execution_time": 600},
        )

    qualifying: dict[int, ProductionTrafficSignal] = {}
    # Teams that surfaced evidence but no production host: candidates for the
    # mobile/server legs, resolved after the (properties-reading) mobile pass.
    pending: dict[int, tuple[int, int]] = {}  # team_id -> (server_lib_users, mobile_candidate_users)
    for team_id, candidate_hosts, mobile_candidate_users, server_lib_users in rows:
        production_host = next((host for host in candidate_hosts if is_production_host(host)), None)
        if production_host is not None:
            qualifying[team_id] = ProductionTrafficSignal(kind="production_host", production_host=production_host)
        else:
            pending[team_id] = (server_lib_users, mobile_candidate_users)

    # Pass 2 — mobile leg, the only one that reads `properties`. Scoped to teams
    # that didn't qualify on the web leg and have enough distinct mobile users to
    # possibly cross the threshold, keeping the full-blob scan off the
    # high-volume web/server teams above.
    mobile_candidates = [
        team_id
        for team_id, (_server_lib_users, mobile_candidate_users) in pending.items()
        if mobile_candidate_users >= MOBILE_LIB_USERS_THRESHOLD
    ]
    mobile_users_by_team = _teams_with_mobile_users(mobile_candidates, lib_expr, workload, use_new)

    # Resolve the mobile/server legs for the pending teams, mobile first to keep
    # the documented web > mobile > server precedence.
    for team_id, (server_lib_users, _mobile_candidate_users) in pending.items():
        mobile_users = mobile_users_by_team.get(team_id)
        if mobile_users is not None:
            qualifying[team_id] = ProductionTrafficSignal(kind="mobile_lib_users", distinct_count=mobile_users)
        elif server_lib_users >= SERVER_LIB_USERS_THRESHOLD:
            qualifying[team_id] = ProductionTrafficSignal(kind="server_lib_users", distinct_count=server_lib_users)

    # Resolve the web leg's conversion instant. Done as a second, narrowly
    # scoped query (only the teams that just qualified on the web leg, only
    # their chosen host) so query 1's full-batch scan and per-team host cap stay
    # untouched. Mobile/server keep `converted_at=None` — their qualifying
    # moment is a windowed threshold-crossing the transition doesn't need.
    web_team_hosts: dict[int, str] = {}
    for team_id, signal in qualifying.items():
        if signal.kind == "production_host" and signal.production_host is not None:
            web_team_hosts[team_id] = signal.production_host
    if web_team_hosts:
        for team_id, converted_at in _earliest_production_host_timestamps(
            web_team_hosts, host_expr, current_url_expr, workload, use_new
        ).items():
            qualifying[team_id] = replace(qualifying[team_id], converted_at=converted_at)

    return qualifying


def _teams_with_mobile_users(
    team_ids: list[int],
    lib_expr: str,
    workload: Workload,
    use_new_events_schema: bool,
) -> dict[int, int]:
    """Distinct mobile-SDK users per team (excluding emulator-flagged events),
    for the teams that cross the mobile threshold.

    The user-diversity proxy for the mobile leg. Mobile SDKs don't put a stable
    per-device id in event properties, so `distinct_id` (the anonymous,
    device-scoped id) is the unit. This is the only leg that reads `properties`:
    `$is_emulator` is matched against its raw JSON value to DROP events
    affirmatively flagged as emulators (`true`/`"true"`) — events without the
    flag are kept, since most mobile events don't carry it. JSONExtractRaw forces
    a full `properties` read, so the caller scopes `team_ids` to the residual set
    of not-yet-qualified teams with enough mobile users to keep that read small.
    """
    if not team_ids:
        return {}

    # events_json stores properties as native JSON; serialize back to a String document for JSONExtractRaw.
    properties_doc = "toJSONString(properties)" if use_new_events_schema else "properties"

    # As in `_teams_meeting_criterion`: the interpolated fragment is a
    # server-side SQL expression from get_property_string_expr, never user
    # input; all values go through query parameters.
    query = f"""
        SELECT
            team_id,
            uniqIf(
                distinct_id,
                lib IN %(mobile_side_libs)s
                AND is_emulator_raw NOT IN ('true', '"true"')
            ) AS mobile_lib_users
        FROM (
            SELECT
                team_id,
                distinct_id,
                {lib_expr} AS lib,
                JSONExtractRaw({properties_doc}, '$is_emulator') AS is_emulator_raw
            FROM {events_read_table(use_new_events_schema)}
            WHERE team_id IN %(team_ids)s
              AND timestamp >= now() - toIntervalDay(%(window_days)s)
        )
        GROUP BY team_id
        HAVING mobile_lib_users >= %(mobile_threshold)s
    """
    with tags_context(product=Product.GROWTH, feature=Feature.ENRICHMENT):
        rows = sync_execute(
            query,
            {
                "team_ids": team_ids,
                "window_days": WINDOW_DAYS,
                "mobile_side_libs": list(MOBILE_SIDE_LIBS),
                "mobile_threshold": MOBILE_LIB_USERS_THRESHOLD,
            },
            workload=workload,
            settings={"max_execution_time": 600},
        )
    return dict(rows)


def _earliest_production_host_timestamps(
    team_hosts: Mapping[int, str],
    host_expr: str,
    current_url_expr: str,
    workload: Workload,
    use_new_events_schema: bool,
) -> dict[int, datetime]:
    """Earliest in-window event timestamp per (team, qualifying production host).

    This is the web-leg activation instant — when the team's first visible
    production event happened — used to stamp the emitted analytics event so the
    milestone lands at conversion time rather than at sweep time.

    Scoped to the already-qualified web-leg teams and their chosen hosts via the
    `team_id` primary-key prefix, so this scan touches only that small subset.
    Uses `timestamp` (event time, the same column the window filters on), not
    `_timestamp` (ingestion time), to keep the instant consistent with the rest
    of the criterion; the trailing-window filter already bounds how far back a
    client-reported time can pull it.
    """
    if not team_hosts:
        return {}

    # `host IN (...)` rather than a `(team_id, host)` tuple-IN: a flat string
    # list is the same parameter shape the criterion query already relies on.
    # A host shared across teams over-matches harmlessly — rows are keyed by
    # (team_id, host) below and only the team's own chosen host is read back.
    production_hosts = list(set(team_hosts.values()))
    # As in `_teams_meeting_criterion`: the interpolated fragments are
    # server-side SQL expressions from get_property_string_expr, never user
    # input; all values go through query parameters.
    query = f"""
        SELECT team_id, host, min(timestamp) AS converted_at
        FROM (
            SELECT
                team_id,
                substring(
                    if({host_expr} != '', {host_expr}, domain({current_url_expr})),
                    1,
                    %(host_length_cap)s
                ) AS host,
                timestamp
            FROM {events_read_table(use_new_events_schema)}
            WHERE team_id IN %(team_ids)s
              AND timestamp >= now() - toIntervalDay(%(window_days)s)
        )
        WHERE host IN %(production_hosts)s
        GROUP BY team_id, host
    """
    with tags_context(product=Product.GROWTH, feature=Feature.ENRICHMENT):
        rows = sync_execute(
            query,
            {
                "team_ids": list(team_hosts.keys()),
                "production_hosts": production_hosts,
                "window_days": WINDOW_DAYS,
                "host_length_cap": SQL_HOST_LENGTH_CAP,
            },
            workload=workload,
            settings={"max_execution_time": 600},
        )

    converted_at_by_team_host = {(team_id, host): converted_at for team_id, host, converted_at in rows}
    result: dict[int, datetime] = {}
    for team_id, host in team_hosts.items():
        converted_at = converted_at_by_team_host.get((team_id, host))
        if converted_at is not None:
            # ClickHouse DateTime is UTC; coerce naive driver values to aware so
            # the PostHog client doesn't guess a timezone at capture time.
            result[team_id] = converted_at if converted_at.tzinfo else converted_at.replace(tzinfo=UTC)
    return result


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
                    # Conversion time for the web leg; run time otherwise. Either
                    # way explicit, so the milestone never drifts to the SDK's
                    # default (the flush-loop wall clock) — see `converted_at`.
                    timestamp=signal.converted_at or now,
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
