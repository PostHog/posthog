import json
import uuid
import random
from datetime import timedelta
from typing import Any
from zoneinfo import ZoneInfo

from django.core.management.base import BaseCommand
from django.utils import timezone
from django.utils.text import slugify

from nanoid import generate

from posthog.clickhouse.client import sync_execute
from posthog.constants import PRODUCT_TOUR_TARGETING_FLAG_PREFIX
from posthog.models import FeatureFlag, Team, User
from posthog.models.event.sql import BULK_INSERT_EVENT_SQL
from posthog.models.person.person import Person, PersonDistinctId

from products.product_tours.backend.models import ProductTour

# Sample step content for generating realistic tours
TOUR_TEMPLATES: list[dict[str, Any]] = [
    {
        "name": "Welcome Tour",
        "description": "Introduce new users to the main features",
        "steps": [
            {"selector": "#nav-dashboards", "content": "Start by exploring your dashboards"},
            {"selector": "#create-insight-btn", "content": "Create your first insight here"},
            {"selector": "#settings-menu", "content": "Configure your preferences in settings"},
        ],
    },
    {
        "name": "Feature Flags Onboarding",
        "description": "Learn how to use feature flags",
        "steps": [
            {
                "selector": "[data-attr='feature-flags-tab']",
                "content": "Feature flags let you control feature rollouts",
            },
            {"selector": "#create-flag-btn", "content": "Click here to create your first flag"},
            {"selector": "#flag-conditions", "content": "Set conditions for who sees the feature"},
            {"selector": "#flag-payloads", "content": "Add payloads for dynamic configuration"},
        ],
    },
    {
        "name": "Analytics Deep Dive",
        "description": "Master the analytics features",
        "steps": [
            {"selector": "#trends-tab", "content": "Trends show how metrics change over time"},
            {"selector": "#funnels-tab", "content": "Funnels help you analyze conversion rates"},
            {"selector": "#retention-tab", "content": "Retention shows how users come back"},
            {"selector": "#paths-tab", "content": "Paths reveal user navigation patterns"},
            {"selector": "#stickiness-tab", "content": "Stickiness measures engagement frequency"},
        ],
    },
    {
        "name": "Session Recordings Guide",
        "description": "Learn to use session recordings effectively",
        "steps": [
            {"selector": "#recordings-list", "content": "Browse recordings of user sessions"},
            {"selector": "#recording-filters", "content": "Filter recordings by events and properties"},
            {"selector": "#recording-player", "content": "Watch recordings with full playback controls"},
        ],
    },
    {
        "name": "Data Pipeline Setup",
        "description": "Configure your data pipeline",
        "steps": [
            {"selector": "#sources-tab", "content": "Connect your data sources here"},
            {"selector": "#transformations", "content": "Transform data before it reaches PostHog"},
            {"selector": "#destinations", "content": "Send data to external destinations"},
            {"selector": "#batch-exports", "content": "Set up batch exports to your data warehouse"},
        ],
    },
    {
        "name": "Experiment Creation",
        "description": "Run your first A/B test",
        "steps": [
            {"selector": "#experiments-tab", "content": "Experiments help you test hypotheses"},
            {"selector": "#new-experiment-btn", "content": "Create a new experiment"},
            {"selector": "#experiment-variants", "content": "Define your control and test variants"},
            {"selector": "#experiment-metrics", "content": "Choose metrics to measure success"},
            {"selector": "#experiment-launch", "content": "Launch when ready to start collecting data"},
        ],
    },
]


class PersonData:
    """Holds person data for event generation."""

    def __init__(self, distinct_id: str, person_uuid: str, properties: dict, created_at: Any):
        self.distinct_id = distinct_id
        self.person_uuid = person_uuid
        self.properties = properties
        self.created_at = created_at


class Command(BaseCommand):
    help = "Generate random product tours for development purposes"

    def create_internal_targeting_flag(self, tour: ProductTour, team: Team, user: User) -> None:
        """Create the internal targeting flag for a product tour."""
        random_id = generate("0123456789abcdef", 8)
        flag_key = f"{PRODUCT_TOUR_TARGETING_FLAG_PREFIX}{slugify(tour.name)}-{random_id}"

        tour_key = str(tour.id)
        filters = {
            "groups": [
                {
                    "variant": "",
                    "rollout_percentage": 100,
                    "properties": [
                        {
                            "key": f"$product_tour_completed/{tour_key}",
                            "type": "person",
                            "value": "is_not_set",
                            "operator": "is_not_set",
                        },
                        {
                            "key": f"$product_tour_dismissed/{tour_key}",
                            "type": "person",
                            "value": "is_not_set",
                            "operator": "is_not_set",
                        },
                    ],
                }
            ]
        }

        flag = FeatureFlag.objects.create(
            team=team,
            key=flag_key,
            name=f"Product Tour: {tour.name}",
            filters=filters,
            active=bool(tour.start_date) and not tour.archived,
            created_by=user,
        )

        tour.internal_targeting_flag = flag
        tour.save(update_fields=["internal_targeting_flag"])

    def get_real_persons(self, team: Team, limit: int = 50) -> list[PersonData]:
        """Fetch real persons from the database."""
        persons_data: list[PersonData] = []

        persons = (
            Person.objects.filter(team_id=team.id)
            .prefetch_related("persondistinctid_set")
            .order_by("-created_at")[:limit]
        )

        for person in persons:
            distinct_ids = PersonDistinctId.objects.filter(person=person, team_id=team.id).values_list(
                "distinct_id", flat=True
            )

            if distinct_ids:
                persons_data.append(
                    PersonData(
                        distinct_id=distinct_ids[0],
                        person_uuid=str(person.uuid),
                        properties=person.properties or {},
                        created_at=person.created_at,
                    )
                )

        return persons_data

    def add_arguments(self, parser):
        parser.add_argument("count", type=int, help="Number of product tours to generate")
        parser.add_argument("--team-id", type=int, help="Team ID to create tours for")
        parser.add_argument(
            "--events",
            type=int,
            default=0,
            help="Number of tour interaction events to generate per tour (default: 0)",
        )
        parser.add_argument(
            "--days-back",
            type=int,
            default=30,
            help="Generate events over the last N days (default: 30)",
        )

    def generate_random_tour(self, team_id: int, user_id: int) -> dict[str, Any]:
        """Generate a random product tour."""
        template = random.choice(TOUR_TEMPLATES)

        # Randomly select a subset of steps (at least 2)
        template_steps: list[dict[str, str]] = template["steps"]
        num_steps = random.randint(2, len(template_steps))
        selected_steps = random.sample(template_steps, num_steps)

        steps = []
        for step in selected_steps:
            steps.append(
                {
                    "selector": step["selector"],
                    "content": {
                        "type": "doc",
                        "content": [{"type": "paragraph", "content": [{"type": "text", "text": step["content"]}]}],
                    },
                    "position": random.choice(["top", "bottom", "left", "right"]),
                }
            )

        # Randomly add URL conditions
        conditions = {}
        if random.random() > 0.5:
            conditions = {
                "url": random.choice(["/dashboard", "/insights", "/feature-flags", "/experiments", "/recordings"]),
                "urlMatchType": random.choice(["contains", "exact"]),
            }

        return {
            "team_id": team_id,
            "name": f"{template['name']} #{random.randint(1, 999)}",
            "description": template["description"],
            "content": {
                "steps": steps,
                "conditions": conditions,
                "appearance": {
                    "backgroundColor": "#ffffff",
                    "textColor": "#000000",
                    "buttonColor": "#1d4aff",
                },
            },
            "created_by_id": user_id,
            "archived": False,
            "start_date": timezone.now() - timedelta(days=random.randint(1, 60)),
            "end_date": None,
        }

    def _build_event_row(
        self,
        event_name: str,
        properties: dict[str, Any],
        person_data: PersonData,
        timestamp: Any,
        team: Team,
        index: int,
    ) -> tuple[str, dict[str, Any]]:
        """Build a single event row for bulk insertion."""
        ts_str = timestamp.astimezone(ZoneInfo("UTC")).strftime("%Y-%m-%d %H:%M:%S.%f")
        ts_str_no_micro = timestamp.astimezone(ZoneInfo("UTC")).strftime("%Y-%m-%d %H:%M:%S")
        zero_date = "1970-01-01 00:00:00"

        person_created_at_str = zero_date
        if person_data.created_at:
            person_created_at_str = person_data.created_at.astimezone(ZoneInfo("UTC")).strftime("%Y-%m-%d %H:%M:%S")

        insert = """(
            %(uuid_{i})s,
            %(event_{i})s,
            %(properties_{i})s,
            %(timestamp_{i})s,
            %(team_id_{i})s,
            %(distinct_id_{i})s,
            %(elements_chain_{i})s,
            %(person_id_{i})s,
            %(person_properties_{i})s,
            %(person_created_at_{i})s,
            %(group0_properties_{i})s,
            %(group1_properties_{i})s,
            %(group2_properties_{i})s,
            %(group3_properties_{i})s,
            %(group4_properties_{i})s,
            %(group0_created_at_{i})s,
            %(group1_created_at_{i})s,
            %(group2_created_at_{i})s,
            %(group3_created_at_{i})s,
            %(group4_created_at_{i})s,
            %(person_mode_{i})s,
            %(created_at_{i})s,
            %(_timestamp_{i})s,
            0
        )""".format(i=index)

        params = {
            f"uuid_{index}": str(uuid.uuid4()),
            f"event_{index}": event_name,
            f"properties_{index}": json.dumps(properties),
            f"timestamp_{index}": ts_str,
            f"team_id_{index}": team.id,
            f"distinct_id_{index}": person_data.distinct_id,
            f"elements_chain_{index}": "",
            f"person_id_{index}": person_data.person_uuid,
            f"person_properties_{index}": json.dumps(person_data.properties),
            f"person_created_at_{index}": person_created_at_str,
            f"group0_properties_{index}": "",
            f"group1_properties_{index}": "",
            f"group2_properties_{index}": "",
            f"group3_properties_{index}": "",
            f"group4_properties_{index}": "",
            f"group0_created_at_{index}": zero_date,
            f"group1_created_at_{index}": zero_date,
            f"group2_created_at_{index}": zero_date,
            f"group3_created_at_{index}": zero_date,
            f"group4_created_at_{index}": zero_date,
            f"person_mode_{index}": "full",
            f"created_at_{index}": ts_str,
            f"_timestamp_{index}": ts_str_no_micro,
        }

        return insert, params

    def generate_tour_events(
        self, tour: ProductTour, team: Team, num_events: int, days_back: int, persons_data: list[PersonData]
    ) -> dict[str, int]:
        """Generate product tour events.

        Returns dict with counts of each event type.
        """
        if not persons_data:
            self.stdout.write(
                self.style.WARNING(
                    "No persons found in the database. Run 'hogli dev:demo-data' first to generate persons."
                )
            )
            return {}

        now = timezone.now()
        steps = tour.content.get("steps", []) if tour.content else []
        num_steps = len(steps)

        if num_steps == 0:
            return {}

        counts = {
            "tour_shown": 0,
            "step_shown": 0,
            "step_completed": 0,
            "tour_completed": 0,
            "tour_dismissed": 0,
        }

        inserts: list[str] = []
        params: dict[str, Any] = {}
        event_index = 0

        for _ in range(num_events):
            person_data = random.choice(persons_data)
            base_timestamp = now - timedelta(
                days=random.randint(0, days_back),
                hours=random.randint(0, 23),
                minutes=random.randint(0, 59),
            )

            # Tour shown event
            insert, event_params = self._build_event_row(
                event_name="product tour shown",
                properties={
                    "$product_tour_id": str(tour.id),
                    "$product_tour_name": tour.name,
                },
                person_data=person_data,
                timestamp=base_timestamp,
                team=team,
                index=event_index,
            )
            inserts.append(insert)
            params.update(event_params)
            event_index += 1
            counts["tour_shown"] += 1

            # Simulate user progressing through steps
            # Random drop-off: some complete all, some drop off at various steps
            completion_probability = random.random()
            steps_to_complete = num_steps if completion_probability > 0.3 else random.randint(0, num_steps - 1)

            current_time = base_timestamp
            for step_order in range(num_steps):
                current_time += timedelta(seconds=random.randint(2, 30))

                # Step shown event
                insert, event_params = self._build_event_row(
                    event_name="product tour step shown",
                    properties={
                        "$product_tour_id": str(tour.id),
                        "$product_tour_name": tour.name,
                        "$product_tour_step_order": step_order,
                    },
                    person_data=person_data,
                    timestamp=current_time,
                    team=team,
                    index=event_index,
                )
                inserts.append(insert)
                params.update(event_params)
                event_index += 1
                counts["step_shown"] += 1

                if step_order < steps_to_complete:
                    current_time += timedelta(seconds=random.randint(3, 60))

                    # Step completed event
                    insert, event_params = self._build_event_row(
                        event_name="product tour step completed",
                        properties={
                            "$product_tour_id": str(tour.id),
                            "$product_tour_name": tour.name,
                            "$product_tour_step_order": step_order,
                        },
                        person_data=person_data,
                        timestamp=current_time,
                        team=team,
                        index=event_index,
                    )
                    inserts.append(insert)
                    params.update(event_params)
                    event_index += 1
                    counts["step_completed"] += 1
                else:
                    # User dropped off - generate dismissed event
                    current_time += timedelta(seconds=random.randint(1, 10))
                    insert, event_params = self._build_event_row(
                        event_name="product tour dismissed",
                        properties={
                            "$product_tour_id": str(tour.id),
                            "$product_tour_name": tour.name,
                            "$product_tour_step_order": step_order,
                            "$product_tour_dismiss_reason": random.choice(["closed", "clicked_outside", "timeout"]),
                        },
                        person_data=person_data,
                        timestamp=current_time,
                        team=team,
                        index=event_index,
                    )
                    inserts.append(insert)
                    params.update(event_params)
                    event_index += 1
                    counts["tour_dismissed"] += 1
                    break

            # If completed all steps, generate tour completed event
            if steps_to_complete == num_steps:
                current_time += timedelta(seconds=random.randint(1, 5))
                insert, event_params = self._build_event_row(
                    event_name="product tour completed",
                    properties={
                        "$product_tour_id": str(tour.id),
                        "$product_tour_name": tour.name,
                        "$product_tour_steps_count": num_steps,
                    },
                    person_data=person_data,
                    timestamp=current_time,
                    team=team,
                    index=event_index,
                )
                inserts.append(insert)
                params.update(event_params)
                event_index += 1
                counts["tour_completed"] += 1

        # Bulk insert all events
        if inserts:
            sql = BULK_INSERT_EVENT_SQL() + ",".join(inserts)
            sync_execute(sql, params)

        return counts

    def handle(self, *args, **options):
        count = options["count"]
        team_id = options["team_id"]
        num_events = options["events"]
        days_back = options["days_back"]

        if team_id:
            team = Team.objects.filter(id=team_id).first()
            if not team:
                self.stdout.write(self.style.ERROR(f"Team with ID {team_id} not found."))
                return
        else:
            team = Team.objects.first()
            if not team:
                self.stdout.write(self.style.ERROR("No teams found. Please create a team first."))
                return

        user = User.objects.filter(current_team_id=team.id).first()
        if not user:
            user = team.organization.members.first()
        if not user:
            self.stdout.write(self.style.ERROR(f"No users found for team {team.id}"))
            return

        # Fetch real persons if events are requested
        persons_data: list[PersonData] = []
        if num_events > 0:
            persons_data = self.get_real_persons(team, limit=100)
            if persons_data:
                self.stdout.write(
                    self.style.SUCCESS(f"Found {len(persons_data)} persons in the database to use for events")
                )
            else:
                self.stdout.write(
                    self.style.WARNING(
                        "No persons found in the database. Run 'hogli dev:demo-data' first to generate persons."
                    )
                )

        total_counts: dict[str, int] = {}

        for _ in range(count):
            tour_data = self.generate_random_tour(team.id, user.id)
            tour = ProductTour.objects.create(**tour_data)
            self.create_internal_targeting_flag(tour, team, user)

            self.stdout.write(self.style.SUCCESS(f'Created product tour "{tour.name}" (ID: {tour.id})'))

            if num_events > 0 and persons_data:
                counts = self.generate_tour_events(tour, team, num_events, days_back, persons_data)
                for key, value in counts.items():
                    total_counts[key] = total_counts.get(key, 0) + value
                self.stdout.write(f"  Generated events: {counts}")

        if num_events > 0 and total_counts:
            self.stdout.write(self.style.SUCCESS(f"\nTotal events generated: {total_counts}"))

        self.stdout.write(
            self.style.SUCCESS(
                f"\nUsage: python manage.py generate_random_product_tours <count> --events <num> --days-back <days>"
            )
        )
