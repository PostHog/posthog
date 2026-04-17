"""Generate synthetic metric events + matching insights for the Anomalies tab.

Creates a catalog of ~30 synthetic metric archetypes with realistic time-series
shapes (seasonal, trending, sparse, flat-drift, weekly cycle, steady-low) and
injects a mix of anomaly types (spikes, drops, sustained shifts, ramps, flash
bursts, flat-lines) at deterministic positions.

For each metric, one aggregated `$demo_metric` event is written per hour over
the past `--days-back` days (default 90). Each event carries a numeric `value`
property equal to the synthetic count at that hour — insights aggregate this
via `sum(properties.value)`.

Three insights are created per metric (hourly / daily / weekly intervals),
each marked viewed so the anomalies replay + Temporal pipeline picks them up.

Usage:
    python manage.py generate_anomaly_demo --team-id=1
    python manage.py generate_anomaly_demo --team-id=1 --dry-run  # no writes

After running, score via:
    python manage.py replay_anomaly_scoring --team-id=1 --wipe-scores
"""
# ruff: noqa: T201

from __future__ import annotations

import json
import math
import uuid
import random
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Literal

from django.core.management.base import BaseCommand
from django.utils import timezone

from posthog.clickhouse.client import sync_execute
from posthog.models.event.sql import EVENTS_DATA_TABLE
from posthog.models.insight import Insight, InsightViewed
from posthog.models.team import Team

EVENT_NAME = "$demo_metric"
PERSON_POOL_SIZE = 200  # synthetic distinct_ids to round-robin over
BULK_INSERT_BATCH = 5000  # rows per ClickHouse VALUES insert

PatternKind = Literal["seasonal", "steady_low", "trending_up", "flat_drift", "weekly_cycle", "sparse"]
AnomalyKind = Literal["spike", "drop", "sustained_shift", "ramp", "flash", "flat_line"]


@dataclass
class MetricSpec:
    name: str
    category: str
    pattern: PatternKind
    base_value: float  # baseline events/hour (before noise + anomalies)
    noise: float = 0.2  # 0..1 — fraction of base_value added as gaussian noise
    anomalies: list[AnomalyKind] = field(default_factory=list)


# Catalog: ~30 metrics across 5 categories, varied base volumes so the tab
# shows a realistic mix of high- and low-count series.
METRIC_CATALOG: list[MetricSpec] = [
    # Traffic: daily+weekly seasonality, high volume, mostly positive movement
    MetricSpec("page_views", "traffic", "seasonal", 120.0, 0.15, ["spike", "spike", "drop"]),
    MetricSpec("active_sessions", "traffic", "seasonal", 45.0, 0.18, ["sustained_shift"]),
    MetricSpec("signups", "traffic", "trending_up", 8.0, 0.35, ["ramp", "drop"]),
    MetricSpec("api_requests", "traffic", "seasonal", 200.0, 0.10, ["flash"]),
    MetricSpec("bounce_rate", "traffic", "flat_drift", 30.0, 0.12, ["spike"]),
    MetricSpec("search_queries", "traffic", "weekly_cycle", 60.0, 0.20, ["drop", "flash"]),
    # Errors: flat low, occasional big spikes
    MetricSpec("api_500s", "errors", "steady_low", 2.0, 0.8, ["spike", "spike", "spike"]),
    MetricSpec("auth_failures", "errors", "sparse", 1.0, 1.2, ["spike", "spike"]),
    MetricSpec("timeout_errors", "errors", "steady_low", 3.0, 0.7, ["sustained_shift"]),
    MetricSpec("validation_errors", "errors", "steady_low", 5.0, 0.5, ["drop"]),
    MetricSpec("frontend_crashes", "errors", "sparse", 0.5, 1.5, ["spike", "flat_line"]),
    MetricSpec("database_errors", "errors", "steady_low", 1.5, 0.9, ["spike", "drop"]),
    # Performance: stable with occasional level shifts
    MetricSpec("p50_latency_ms", "performance", "flat_drift", 40.0, 0.10, ["sustained_shift"]),
    MetricSpec("p95_latency_ms", "performance", "flat_drift", 180.0, 0.15, ["spike", "spike"]),
    MetricSpec("p99_latency_ms", "performance", "flat_drift", 450.0, 0.25, ["sustained_shift", "spike"]),
    MetricSpec("throughput_rps", "performance", "seasonal", 320.0, 0.12, ["drop"]),
    MetricSpec("cache_hit_rate_pct", "performance", "flat_drift", 92.0, 0.03, ["drop"]),
    MetricSpec("connection_pool_usage", "performance", "flat_drift", 55.0, 0.15, ["ramp"]),
    # Business: weekly cycle + slow trend
    MetricSpec("checkouts", "business", "weekly_cycle", 35.0, 0.18, ["spike"]),
    MetricSpec("revenue_events", "business", "weekly_cycle", 28.0, 0.20, ["drop"]),
    MetricSpec("trial_conversions", "business", "trending_up", 6.0, 0.30, ["drop"]),
    MetricSpec("abandoned_carts", "business", "weekly_cycle", 18.0, 0.25, ["spike", "spike"]),
    MetricSpec("subscription_upgrades", "business", "weekly_cycle", 4.0, 0.40, ["ramp"]),
    MetricSpec("refund_requests", "business", "sparse", 1.5, 1.0, ["spike", "spike"]),
    # User: engagement patterns
    MetricSpec("new_users", "user", "trending_up", 15.0, 0.25, ["drop"]),
    MetricSpec("returning_users", "user", "weekly_cycle", 50.0, 0.15, ["sustained_shift"]),
    MetricSpec("power_users_active", "user", "flat_drift", 12.0, 0.15, ["drop"]),
    MetricSpec("actions_per_session", "user", "flat_drift", 8.0, 0.18, ["sustained_shift"]),
    MetricSpec("feature_clicks", "user", "trending_up", 22.0, 0.25, ["spike", "spike"]),
    MetricSpec("notifications_sent", "user", "weekly_cycle", 40.0, 0.20, ["flat_line"]),
]

INTERVALS = [("hour", "ActionsLineGraph"), ("day", "ActionsLineGraph"), ("week", "ActionsBar")]


class Command(BaseCommand):
    help = "Generate synthetic $demo_metric events + matching insights for anomaly detection testing"

    def add_arguments(self, parser):
        parser.add_argument("--team-id", type=int, required=True)
        parser.add_argument(
            "--days-back", type=int, default=90, help="How many days of historical data to generate (default 90)"
        )
        parser.add_argument("--seed", type=int, default=42, help="Random seed for deterministic output (default 42)")
        parser.add_argument(
            "--wipe-existing",
            action="store_true",
            help="Delete existing $demo_metric events and prior demo insights on this team before regenerating",
        )
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Print what would be generated but don't write to the DB",
        )
        parser.add_argument(
            "--only-insights",
            action="store_true",
            help="Skip event generation; only (re)create the insights. Useful after a prior event run.",
        )

    def handle(self, *args, **options):
        team = Team.objects.get(pk=options["team_id"])
        days_back = options["days_back"]
        rng = random.Random(options["seed"])
        dry_run = options["dry_run"]
        now = datetime.now(UTC)
        start_time = (now - timedelta(days=days_back)).replace(minute=0, second=0, microsecond=0)
        n_hours = int((now - start_time).total_seconds() // 3600)

        print(f"[demo] team {team.id} ({team.name}) — generating {len(METRIC_CATALOG)} metrics × 3 intervals")
        print(f"[demo] window: {start_time:%Y-%m-%d %H:%M} → {now:%Y-%m-%d %H:%M} ({n_hours} hours)")

        if options["wipe_existing"] and not dry_run:
            self._wipe_existing(team)

        # Generate events first so insights have something to query when viewed
        if not options["only_insights"]:
            total_events = self._generate_events(team, rng, start_time, n_hours, dry_run=dry_run)
            print(f"[demo] wrote {total_events} events")
        else:
            print("[demo] --only-insights: skipping event generation")

        # Then create insights
        owner = team.organization.members.first()
        created_insights = self._create_insights(team, owner, dry_run=dry_run)
        print(f"[demo] created {created_insights} insights (and marked viewed)")

        if dry_run:
            print("[demo] dry-run: no changes committed")
        else:
            print(f"[demo] done. Next: python manage.py replay_anomaly_scoring --team-id={team.id} --wipe-scores")

    def _wipe_existing(self, team: Team) -> None:
        # Drop existing demo insights (name prefix is stable) and clean up events
        deleted_insights = Insight.objects.filter(team=team, name__startswith="[demo] ").delete()
        print(f"[demo] deleted prior demo insights: {deleted_insights}")
        sync_execute(
            f"ALTER TABLE {EVENTS_DATA_TABLE()} DELETE WHERE team_id = %(team_id)s AND event = %(event)s",
            {"team_id": team.id, "event": EVENT_NAME},
        )
        print(f"[demo] issued mutation to drop $demo_metric events for team {team.id}")

    def _generate_events(
        self,
        team: Team,
        rng: random.Random,
        start_time: datetime,
        n_hours: int,
        dry_run: bool,
    ) -> int:
        distinct_ids = [f"demo-user-{i:04d}" for i in range(PERSON_POOL_SIZE)]
        person_uuid = str(uuid.uuid4())  # one synthetic person shared across events
        total = 0
        batch: list[dict] = []

        for metric in METRIC_CATALOG:
            series = _build_series(metric, n_hours, rng)
            series = _inject_anomalies(series, metric.anomalies, rng)

            for hour_idx, value in enumerate(series):
                ts = start_time + timedelta(hours=hour_idx)
                # Nudge the timestamp somewhere inside the hour for realism
                ts += timedelta(seconds=rng.randint(60, 3500))
                batch.append(
                    _event_row(
                        team_id=team.id,
                        event_uuid=str(uuid.uuid4()),
                        distinct_id=rng.choice(distinct_ids),
                        person_uuid=person_uuid,
                        timestamp=ts,
                        metric=metric,
                        value=max(0.0, value),
                    )
                )
                total += 1

                if len(batch) >= BULK_INSERT_BATCH:
                    if not dry_run:
                        _bulk_insert_events(batch)
                    batch.clear()

        if batch and not dry_run:
            _bulk_insert_events(batch)

        return total

    def _create_insights(self, team: Team, owner, dry_run: bool) -> int:
        created = 0
        for metric in METRIC_CATALOG:
            for interval, display in INTERVALS:
                name = f"[demo] {metric.name} ({interval})"
                query = _build_trends_query(metric, interval, display)
                if dry_run:
                    created += 1
                    continue

                insight, was_created = Insight.objects.update_or_create(
                    team=team,
                    name=name,
                    defaults={
                        "description": f"{metric.category} — {metric.pattern} — injected: {', '.join(metric.anomalies) or 'none'}",
                        "query": query,
                        "deleted": False,
                        "saved": True,
                        "created_by": owner,
                    },
                )
                # Ensure it shows up in the "recently viewed" filter used by the
                # anomalies pipeline's eligibility check.
                InsightViewed.objects.update_or_create(
                    team=team,
                    insight=insight,
                    user=owner,
                    defaults={"last_viewed_at": timezone.now()},
                )
                created += 1
        return created


# ---------------------------------------------------------------------------
# Pattern generators
# ---------------------------------------------------------------------------


def _build_series(metric: MetricSpec, n_hours: int, rng: random.Random) -> list[float]:
    if metric.pattern == "seasonal":
        return _gen_seasonal(n_hours, metric.base_value, metric.noise, rng)
    if metric.pattern == "steady_low":
        return _gen_steady_low(n_hours, metric.base_value, metric.noise, rng)
    if metric.pattern == "trending_up":
        return _gen_trending_up(n_hours, metric.base_value, metric.noise, rng)
    if metric.pattern == "flat_drift":
        return _gen_flat_drift(n_hours, metric.base_value, metric.noise, rng)
    if metric.pattern == "weekly_cycle":
        return _gen_weekly_cycle(n_hours, metric.base_value, metric.noise, rng)
    if metric.pattern == "sparse":
        return _gen_sparse(n_hours, metric.base_value, metric.noise, rng)
    raise ValueError(f"Unknown pattern: {metric.pattern}")


def _gen_seasonal(n_hours: int, base: float, noise: float, rng: random.Random) -> list[float]:
    """Daily + weekly cycles — traffic-like."""
    out = []
    for h in range(n_hours):
        hour = h % 24
        dow = (h // 24) % 7
        daily = 0.55 + 0.45 * math.cos((hour - 14) * math.pi / 12)  # peak ~2pm
        weekly = 1.0 if dow < 5 else 0.55  # weekends dampened
        value = base * daily * weekly + rng.gauss(0, base * noise)
        out.append(value)
    return out


def _gen_steady_low(n_hours: int, base: float, noise: float, rng: random.Random) -> list[float]:
    """Low flat baseline, mild seasonality. Good for errors / low-count metrics."""
    out = []
    for h in range(n_hours):
        hour = h % 24
        daily = 0.85 + 0.15 * math.cos((hour - 10) * math.pi / 12)
        value = base * daily + rng.gauss(0, max(0.3, base * noise))
        out.append(value)
    return out


def _gen_trending_up(n_hours: int, base: float, noise: float, rng: random.Random) -> list[float]:
    """Linear growth with mild daily cycle."""
    out = []
    for h in range(n_hours):
        growth = 1.0 + (h / n_hours) * 0.8  # 1.0 → 1.8
        hour = h % 24
        daily = 0.85 + 0.15 * math.cos((hour - 12) * math.pi / 12)
        value = base * growth * daily + rng.gauss(0, base * noise)
        out.append(value)
    return out


def _gen_flat_drift(n_hours: int, base: float, noise: float, rng: random.Random) -> list[float]:
    """Roughly flat with slow sinusoidal drift. Good for latency / perf metrics."""
    out = []
    for h in range(n_hours):
        drift = math.sin(h / (24 * 14) * math.pi * 2) * 0.10  # 2-week period, ±10%
        value = base * (1.0 + drift) + rng.gauss(0, base * noise)
        out.append(value)
    return out


def _gen_weekly_cycle(n_hours: int, base: float, noise: float, rng: random.Random) -> list[float]:
    """Strong weekly cycle, mild growth. Business-like."""
    out = []
    for h in range(n_hours):
        dow = (h // 24) % 7
        hour = h % 24
        weekly = 0.55 + 0.45 * math.cos((dow - 2) * math.pi / 3.5)  # peak Tue/Wed
        daily = 0.8 + 0.2 * math.cos((hour - 13) * math.pi / 12)
        growth = 1.0 + (h / n_hours) * 0.15
        value = base * weekly * daily * growth + rng.gauss(0, base * noise)
        out.append(value)
    return out


def _gen_sparse(n_hours: int, base: float, noise: float, rng: random.Random) -> list[float]:
    """Mostly zero with occasional small counts. Good for rare events."""
    out = []
    for _ in range(n_hours):
        if rng.random() < 0.12:  # 12% of hours have activity
            value = base * (0.5 + rng.random() * 2.0) + rng.gauss(0, base * noise * 0.3)
        else:
            value = 0.0
        out.append(value)
    return out


# ---------------------------------------------------------------------------
# Anomaly injectors
# ---------------------------------------------------------------------------


def _inject_anomalies(series: list[float], kinds: list[AnomalyKind], rng: random.Random) -> list[float]:
    """Inject anomalies at varied positions, avoiding the last ~5% of the series.

    The tail is left clean so the replay's latest-point scoring doesn't always
    find a planted anomaly at `now`.
    """
    n = len(series)
    safe_tail_start = int(n * 0.95)
    series = list(series)  # copy

    for kind in kinds:
        # Place anomalies after an initial warmup (10% in) so the detector has history
        at = rng.randint(int(n * 0.1), safe_tail_start - 1)
        if kind == "spike":
            magnitude = rng.uniform(4.0, 8.0)
            series[at] = max(series[at], 1.0) * magnitude
        elif kind == "drop":
            series[at] = 0.0
        elif kind == "sustained_shift":
            length = rng.randint(48, 24 * 7)  # 2-7 days of shifted data
            multiplier = rng.choice([rng.uniform(0.3, 0.6), rng.uniform(1.6, 2.4)])
            for i in range(at, min(at + length, safe_tail_start)):
                series[i] *= multiplier
        elif kind == "ramp":
            length = rng.randint(24 * 3, 24 * 10)  # 3-10 day ramp
            peak = rng.uniform(1.8, 3.0)
            for i in range(length):
                idx = at + i
                if idx >= safe_tail_start:
                    break
                t = i / max(length - 1, 1)
                series[idx] *= 1.0 + (peak - 1.0) * t
        elif kind == "flash":
            length = rng.randint(4, 12)
            peak = max(series) if series else 1.0
            for i in range(length):
                idx = at + i
                if idx >= safe_tail_start:
                    break
                series[idx] = rng.uniform(0, peak * 2.0)
        elif kind == "flat_line":
            length = rng.randint(24, 24 * 3)
            for i in range(at, min(at + length, safe_tail_start)):
                series[i] = 0.0
    return series


# ---------------------------------------------------------------------------
# Event / insight shaping
# ---------------------------------------------------------------------------


def _event_row(
    *,
    team_id: int,
    event_uuid: str,
    distinct_id: str,
    person_uuid: str,
    timestamp: datetime,
    metric: MetricSpec,
    value: float,
) -> dict:
    ts_str = timestamp.astimezone(UTC).strftime("%Y-%m-%d %H:%M:%S.%f")
    return {
        "uuid": event_uuid,
        "event": EVENT_NAME,
        "properties": json.dumps(
            {
                "metric_name": metric.name,
                "metric_category": metric.category,
                "value": round(value, 3),
            }
        ),
        "timestamp": ts_str,
        "team_id": team_id,
        "distinct_id": distinct_id,
        "person_id": person_uuid,
        "created_at": ts_str,
    }


def _bulk_insert_events(rows: list[dict]) -> None:
    """Batch INSERT into writable_events via sync_execute.

    Writes a minimal column set — uuid, event, properties, timestamp, team_id,
    distinct_id, created_at, person_id. Everything else takes the table's
    default. This matches how PostHog's test helpers insert synthetic events
    directly rather than routing through Kafka / plugin-server.
    """
    if not rows:
        return
    values_sql_parts = []
    params: dict = {}
    for i, r in enumerate(rows):
        values_sql_parts.append(
            f"""(
                %(uuid_{i})s,
                %(event_{i})s,
                %(properties_{i})s,
                %(timestamp_{i})s,
                %(team_id_{i})s,
                %(distinct_id_{i})s,
                %(created_at_{i})s,
                %(person_id_{i})s
            )"""
        )
        params[f"uuid_{i}"] = r["uuid"]
        params[f"event_{i}"] = r["event"]
        params[f"properties_{i}"] = r["properties"]
        params[f"timestamp_{i}"] = r["timestamp"]
        params[f"team_id_{i}"] = r["team_id"]
        params[f"distinct_id_{i}"] = r["distinct_id"]
        params[f"created_at_{i}"] = r["created_at"]
        params[f"person_id_{i}"] = r["person_id"]

    sql = f"""
INSERT INTO {EVENTS_DATA_TABLE()}
(uuid, event, properties, timestamp, team_id, distinct_id, created_at, person_id)
VALUES {", ".join(values_sql_parts)}
"""
    sync_execute(sql, params)


def _build_trends_query(metric: MetricSpec, interval: str, display: str) -> dict:
    date_from = {"hour": "-7d", "day": "-30d", "week": "-90d"}[interval]
    return {
        "kind": "InsightVizNode",
        "source": {
            "kind": "TrendsQuery",
            "series": [
                {
                    "kind": "EventsNode",
                    "math": "sum",
                    "math_property": "value",
                    "name": EVENT_NAME,
                    "event": EVENT_NAME,
                    "properties": [
                        {
                            "key": "metric_name",
                            "value": metric.name,
                            "operator": "exact",
                            "type": "event",
                        },
                    ],
                }
            ],
            "interval": interval,
            "dateRange": {"date_from": date_from},
            "trendsFilter": {"display": display},
            "properties": [],
            "filterTestAccounts": False,
        },
    }
