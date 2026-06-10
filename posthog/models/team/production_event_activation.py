"""
Detection of whether a team has begun ingesting real production traffic.

This is the activation milestone behind `Team.ingested_production_event`. The
file is split into two layers so the heuristic can be retuned without
touching the rest of the system:

  1. CRITERION  — `_teams_meeting_criterion(team_ids)` is the single source
                  of truth for what counts as "production traffic": at least
                  one event in the window whose origin host is a real public
                  host (see `is_production_host`). The contract is
                  intentionally narrow: `Iterable[team_id] -> dict[team_id,
                  production_host]`. The implementation is free to change.

  2. TRANSITION — `_mark_teams_ingested_production_event(hosts, now)` is
                  the only code that marks the column and emits the
                  `first team production event ingested` analytics event.
                  Idempotent under concurrent runs via `SELECT FOR UPDATE
                  SKIP LOCKED`.

Scheduling lives in `products/growth/dags/team_production_event_activation.py`,
which wires these helpers into a Dagster job + daily schedule.

Detection is fail-closed: a team qualifies only on a positive public-host
signal from the browser's `$host` / `$current_url`. No host (server-side and
mobile SDKs), anything local/private/reserved, or anything ambiguous does not
qualify. A false positive silently corrupts the activation metric and is hard
to detect; a false negative is recoverable — the daily sweep re-checks
unflagged teams. `$ip`/GeoIP can't be used instead: a developer's local
backend still reaches us over the public internet from a public IP.
"""

from collections.abc import Iterable, Mapping
from datetime import datetime
from ipaddress import IPv4Address, IPv6Address, ip_address
from typing import Final

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


def _teams_meeting_criterion(team_ids: Iterable[int]) -> dict[int, str]:
    """Return `{team_id: production_host}` for the subset of `team_ids` whose
    recent traffic meets the criterion: at least one event in the window with
    a production origin host.

    Single source of truth for "what counts as production traffic." ClickHouse
    only collects candidate hosts — `$host`, falling back to the host of
    `$current_url` — per team; classification happens in `is_production_host`
    so it stays unit-testable. The exact-localhost prefilter in SQL is an
    optimization only (it keeps the dominant dev noise out of the result set
    and away from the per-team cap); correctness lives in the Python classifier.
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
            SELECT team_id, host
            FROM (
                SELECT
                    team_id,
                    if(
                        JSONExtractString(properties, '$host') != '',
                        JSONExtractString(properties, '$host'),
                        domain(JSONExtractString(properties, '$current_url'))
                    ) AS host
                FROM events
                WHERE team_id IN %(team_ids)s
                  AND timestamp >= now() - toIntervalDay(%(window_days)s)
            )
            WHERE host != ''
              AND host != 'localhost'
              AND NOT startsWith(host, 'localhost:')
            GROUP BY team_id, host
            LIMIT %(hosts_per_team_cap)s BY team_id
            """,
            {
                "team_ids": team_id_list,
                "window_days": WINDOW_DAYS,
                "hosts_per_team_cap": HOSTS_PER_TEAM_CAP,
            },
        )

    qualifying: dict[int, str] = {}
    for team_id, host in rows:
        if team_id not in qualifying and is_production_host(host):
            qualifying[team_id] = host
    return qualifying


# --- Transition -------------------------------------------------------------


def _mark_teams_ingested_production_event(team_production_hosts: Mapping[int, str], now: datetime) -> int:
    """Mark `ingested_production_event` for the given teams and emit one
    activation event per team that is newly marked.

    Concurrent-safe via `SELECT FOR UPDATE SKIP LOCKED`: a second run
    running in parallel sees only the rows the first run hasn't locked, so
    each team's event fires at most once. Returns the number of teams that
    were marked this call.
    """
    if not team_production_hosts:
        return 0

    with transaction.atomic():
        teams_to_mark = list(
            Team.objects.select_for_update(skip_locked=True)
            .filter(id__in=list(team_production_hosts.keys()), ingested_production_event=False)
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
            capture(
                distinct_id=str(team.uuid),
                event="first team production event ingested",
                properties={
                    "production_host": team_production_hosts[team.id],
                    "window_days": WINDOW_DAYS,
                },
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

    qualifying_hosts = _teams_meeting_criterion(batch)
    marked = _mark_teams_ingested_production_event(qualifying_hosts, now=now) if qualifying_hosts else 0

    # Bump `_last_checked_at` for the rest so we know we evaluated them.
    # Qualifying teams already had `_last_checked_at` set inside the
    # transition helper, so don't double-write them here.
    non_qualifying = [tid for tid in batch if tid not in qualifying_hosts]
    if non_qualifying:
        Team.objects.filter(id__in=non_qualifying).update(
            ingested_production_event_last_checked_at=now,
        )

    return len(qualifying_hosts), marked
