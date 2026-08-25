"""
Seed a fresh, learnable dataset for local autoresearch end-to-end testing.

Usage:
    CLICKHOUSE_DATABASE=posthog python manage.py autoresearch_seed_demo \\
        --team-id 6 --users 600 --days 90 --seed 1

Writes identified persons plus a "reports" feature narrative straight into
ClickHouse (same path as `generate_demo_data`: persons and distinct ids over
Kafka, events over Kafka). Persons are not written to Postgres, so the persons
list won't show them - autoresearch itself only reads ClickHouse.

Events emitted (all new to a hedgebox team):
    $pageview               activity signal (also lets the built-in templates resolve)
    report_created          feature usage
    collaborator_invited    strong predictor of sharing
    integration_connected   moderate predictor
    pricing_page_viewed     weak predictor
    report_shared           THE TARGET - `share_type` is `external` or `internal`

Also creates an action "Shared a report externally" (report_shared where
share_type = external) so the action-target path can be exercised with a rarer
target than the bare event.

A latent persona (solo / collaborator / power) drives both the feature events
and the share hazard, so a sensible model lands well above baseline AUC.
Every timestamp is relative to now, so the data stays fresh for "last N days"
windows and online validation can mature against it.
"""

from __future__ import annotations

import math
import uuid
import random
from dataclasses import dataclass, field
from datetime import datetime, timedelta

from django.core.management.base import BaseCommand, CommandError
from django.utils import timezone

from posthog.kafka_client.client import ClickhouseProducer
from posthog.kafka_client.routing import get_producer
from posthog.kafka_client.topics import KAFKA_EVENTS_JSON, KAFKA_PERSON, KAFKA_PERSON_DISTINCT_ID
from posthog.models.event.util import create_event
from posthog.models.person.util import create_person, create_person_distinct_id
from posthog.models.team.team import Team
from posthog.uuidt import UUIDT

from products.actions.backend.models.action import Action

TARGET_EVENT = "report_shared"
ACTION_NAME = "Shared a report externally"

PERSONAS: dict[str, dict[str, float]] = {
    # p_active: chance of any activity on a given day; feature rates are per active day.
    "solo": {"weight": 0.45, "p_active": 0.25, "p_report": 0.15, "p_invite": 0.01, "p_integration": 0.02},
    "collaborator": {"weight": 0.35, "p_active": 0.45, "p_report": 0.35, "p_invite": 0.10, "p_integration": 0.06},
    "power": {"weight": 0.20, "p_active": 0.70, "p_report": 0.60, "p_invite": 0.18, "p_integration": 0.15},
}

PLANS = [("free", 0.6), ("team", 0.3), ("enterprise", 0.1)]
ROLES = ["analyst", "engineer", "product_manager", "founder", "marketer"]
COUNTRIES = ["US", "GB", "DE", "FR", "CA", "AU", "BR", "IN"]
SIGNUP_SOURCES = ["organic", "referral", "ads", "docs", "conference"]
COMPANY_SIZES = ["1-10", "11-50", "51-200", "201-1000", "1000+"]
REPORT_TYPES = ["funnel", "trend", "retention", "dashboard"]


@dataclass
class SeedUser:
    person_id: str
    distinct_id: str
    persona: str
    plan: str
    properties: dict[str, str]
    signup_at: datetime
    reports_created: int = 0
    invited_collaborator: bool = False
    integration_connected: bool = False
    viewed_pricing: bool = False
    shares: int = 0
    events: list[tuple[datetime, str, dict[str, object]]] = field(default_factory=list)


def _weighted_choice(rng: random.Random, options: list[tuple[str, float]]) -> str:
    r = rng.random()
    acc = 0.0
    for name, w in options:
        acc += w
        if r <= acc:
            return name
    return options[-1][0]


def _share_probability(user: SeedUser, days_since_signup: int) -> float:
    """Per-active-day hazard of `report_shared`, a logistic over the accumulated features."""
    persona_bias = {"solo": -1.0, "collaborator": 0.3, "power": 0.8}[user.persona]
    z = (
        -6.8
        + persona_bias
        + 0.25 * min(user.reports_created, 8)
        + (1.1 if user.invited_collaborator else 0.0)
        + (0.6 if user.integration_connected else 0.0)
        + (0.3 if user.viewed_pricing else 0.0)
        + (0.5 if user.plan != "free" else 0.0)
        + (0.4 if user.shares > 0 else 0.0)
        - (0.4 if days_since_signup < 3 else 0.0)
    )
    return 1.0 / (1.0 + math.exp(-z))


def _simulate_user(rng: random.Random, index: int, seed: int, now: datetime, days: int) -> SeedUser:
    persona = _weighted_choice(rng, [(name, cfg["weight"]) for name, cfg in PERSONAS.items()])
    cfg = PERSONAS[persona]
    plan = _weighted_choice(rng, PLANS)
    # Deterministic ids so a re-run with the same seed produces the same people.
    person_id = str(uuid.uuid5(uuid.NAMESPACE_URL, f"posthog://autoresearch-seed/{seed}/{index}"))
    distinct_id = f"seed{seed}-user-{index:05d}@example.com"
    signup_at = now - timedelta(days=rng.uniform(10, days), hours=rng.uniform(0, 23))
    properties = {
        "email": distinct_id,
        "name": f"Seed user {index}",
        "plan": plan,
        "role": rng.choice(ROLES),
        "country": rng.choice(COUNTRIES),
        "signup_source": rng.choice(SIGNUP_SOURCES),
        "company_size": rng.choice(COMPANY_SIZES),
    }
    user = SeedUser(
        person_id=person_id,
        distinct_id=distinct_id,
        persona=persona,
        plan=plan,
        properties=properties,
        signup_at=signup_at,
    )

    def emit(ts: datetime, event: str, props: dict[str, object] | None = None) -> None:
        user.events.append((ts, event, props or {}))

    emit(signup_at, "$identify", {"$set": properties})
    emit(signup_at + timedelta(seconds=1), "$pageview", {"$current_url": "https://hedgebox.example.com/welcome"})

    day = 0
    while True:
        day += 1
        day_start = signup_at + timedelta(days=day)
        # A session can run ~16h past day_start; stop before any of it would land in the future.
        if day_start + timedelta(hours=16) >= now:
            break
        if rng.random() > cfg["p_active"]:
            continue

        session_start = day_start + timedelta(hours=rng.uniform(0, 14), minutes=rng.uniform(0, 59))
        cursor = session_start
        for _ in range(rng.randint(1, 4)):
            emit(
                cursor,
                "$pageview",
                {
                    "$current_url": f"https://hedgebox.example.com/{rng.choice(['home', 'reports', 'files', 'settings'])}"
                },
            )
            cursor += timedelta(minutes=rng.uniform(0.5, 6))

        if rng.random() < cfg["p_report"]:
            user.reports_created += 1
            emit(
                cursor,
                "report_created",
                {"report_type": rng.choice(REPORT_TYPES), "report_index": user.reports_created},
            )
            cursor += timedelta(minutes=rng.uniform(1, 5))

        if not user.invited_collaborator and rng.random() < cfg["p_invite"]:
            user.invited_collaborator = True
            emit(cursor, "collaborator_invited", {"invite_count": rng.randint(1, 4)})
            cursor += timedelta(minutes=rng.uniform(1, 3))

        if not user.integration_connected and rng.random() < cfg["p_integration"]:
            user.integration_connected = True
            emit(cursor, "integration_connected", {"integration": rng.choice(["slack", "github", "hubspot", "zapier"])})
            cursor += timedelta(minutes=rng.uniform(1, 3))

        if not user.viewed_pricing and rng.random() < 0.04:
            user.viewed_pricing = True
            emit(cursor, "pricing_page_viewed", {"$current_url": "https://hedgebox.example.com/pricing"})
            cursor += timedelta(minutes=rng.uniform(1, 3))

        # Sharing needs something to share.
        if user.reports_created > 0 and rng.random() < _share_probability(user, day):
            user.shares += 1
            share_type = "external" if rng.random() < (0.55 if user.plan != "free" else 0.3) else "internal"
            emit(
                cursor,
                TARGET_EVENT,
                {"share_type": share_type, "report_type": rng.choice(REPORT_TYPES), "share_index": user.shares},
            )

    return user


def _flush_producers() -> None:
    for topic in (KAFKA_PERSON, KAFKA_PERSON_DISTINCT_ID, KAFKA_EVENTS_JSON):
        get_producer(topic=topic).flush()


class Command(BaseCommand):
    help = "Seed identified persons and a fresh, learnable event narrative into a team for autoresearch e2e testing."

    def add_arguments(self, parser):
        parser.add_argument("--team-id", type=int, required=True, help="Team to seed into.")
        parser.add_argument(
            "--users", type=int, default=600, help="Number of identified persons to create (default: 600)."
        )
        parser.add_argument("--days", type=int, default=90, help="How far back sign-ups start (default: 90).")
        parser.add_argument(
            "--seed", type=int, default=1, help="RNG seed; also namespaces person ids and distinct ids."
        )
        parser.add_argument(
            "--dry-run", action="store_true", help="Simulate and print the summary without writing anything."
        )

    def handle(self, *args, **options):
        team_id = options["team_id"]
        try:
            team = Team.objects.get(pk=team_id)
        except Team.DoesNotExist:
            raise CommandError(f"Team {team_id} not found.")

        seed: int = options["seed"]
        rng = random.Random(seed)
        now = timezone.now()
        users = [_simulate_user(rng, i, seed, now, options["days"]) for i in range(options["users"])]

        total_events = sum(len(u.events) for u in users)
        sharers = sum(1 for u in users if u.shares > 0)
        recent_sharers = sum(
            1 for u in users if any(e == TARGET_EVENT and ts >= now - timedelta(days=30) for ts, e, _ in u.events)
        )
        self.stdout.write(f"\nSeeding team '{team.name}' (id={team_id}) with seed={seed}")
        self.stdout.write(f"  Persons          : {len(users)}")
        self.stdout.write(f"  Events           : {total_events}")
        self.stdout.write(f"  Ever shared      : {sharers} ({sharers / len(users):.1%})")
        self.stdout.write(f"  Shared last 30d  : {recent_sharers}")
        by_persona = {name: sum(1 for u in users if u.persona == name) for name in PERSONAS}
        share_rate = {
            name: (sum(1 for u in users if u.persona == name and u.shares > 0) / max(by_persona[name], 1))
            for name in PERSONAS
        }
        for name in PERSONAS:
            self.stdout.write(f"  {name:<14}: {by_persona[name]:>4} users, {share_rate[name]:.0%} shared")

        if options["dry_run"]:
            self.stdout.write(self.style.WARNING("\nDry run - nothing written."))
            return

        ClickhouseProducer()  # fail fast if Kafka is unreachable
        for i, user in enumerate(users, start=1):
            create_person(
                uuid=user.person_id,
                team_id=team.pk,
                properties=user.properties,
                version=0,
                is_identified=True,
                created_at=user.signup_at,
                timestamp=user.signup_at,
            )
            create_person_distinct_id(team_id=team.pk, distinct_id=user.distinct_id, person_id=user.person_id)
            for ts, event, props in user.events:
                create_event(
                    event_uuid=UUIDT(unix_time_ms=int(ts.timestamp() * 1000)),
                    event=event,
                    team=team,
                    distinct_id=user.distinct_id,
                    timestamp=ts,
                    properties=props,
                    person_id=uuid.UUID(user.person_id),
                    person_properties=user.properties,
                    person_created_at=user.signup_at,
                )
            # Flush in batches so the local producer queue never overflows on large seeds.
            if i % 50 == 0:
                _flush_producers()
                self.stdout.write(f"  ... {i}/{len(users)} persons written")
        _flush_producers()

        action, created = Action.objects.get_or_create(
            team=team,
            name=ACTION_NAME,
            deleted=False,
            defaults={
                "description": f"`{TARGET_EVENT}` with share_type = external. Seeded by autoresearch_seed_demo.",
                "steps_json": [
                    {
                        "event": TARGET_EVENT,
                        "properties": [
                            {"key": "share_type", "type": "event", "value": ["external"], "operator": "exact"}
                        ],
                    }
                ],
            },
        )

        self.stdout.write(self.style.SUCCESS(f"\n✓ Wrote {len(users)} persons and {total_events} events."))
        self.stdout.write(f"  Action '{ACTION_NAME}' id={action.pk} ({'created' if created else 'already existed'})")
        self.stdout.write("\nNext:")
        self.stdout.write(
            f"  CLICKHOUSE_DATABASE=posthog python manage.py autoresearch_validate --team-id {team_id} --target {TARGET_EVENT} --horizon 30"
        )
        self.stdout.write(
            f"  CLICKHOUSE_DATABASE=posthog python manage.py autoresearch_train --create --team-id {team_id} "
            f"--target {TARGET_EVENT} --name 'Report sharing prediction' --horizon 30 --user-id 1 --stub"
        )
