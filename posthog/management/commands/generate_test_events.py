"""
Generate test persons and events with evolving person properties.

Usage:
    ./manage.py generate_test_events --team-id=1 --num-persons=10 --events-per-person=5
"""

import uuid
import random
from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import Enum
from typing import Any

from django.core.management.base import BaseCommand

import structlog

from posthog.api.capture import capture_internal
from posthog.models import Team

logger = structlog.get_logger(__name__)


class PropType(Enum):
    STRING = "string"
    NUMBER = "number"
    BOOLEAN = "boolean"
    DATETIME = "datetime"


@dataclass
class GeneratedProperty:
    """A generated property with its type tracked for mutation."""

    key: str
    value: Any
    prop_type: PropType


@dataclass
class GeneratedPerson:
    """A generated person with distinct_id and properties."""

    distinct_id: str
    set_once_props: list[GeneratedProperty] = field(default_factory=list)
    set_props: list[GeneratedProperty] = field(default_factory=list)

    def get_set_once_dict(self) -> dict[str, Any]:
        return {p.key: p.value for p in self.set_once_props}

    def get_set_dict(self) -> dict[str, Any]:
        return {p.key: p.value for p in self.set_props}


def generate_random_property(key_prefix: str, index: int) -> GeneratedProperty:
    """Generate a random property with a random type."""
    key = f"{key_prefix}_{index}"
    prop_type = random.choice(list(PropType))

    value: Any
    if prop_type == PropType.STRING:
        value = f"initial_value_{random.randint(1000, 9999)}"
    elif prop_type == PropType.NUMBER:
        value = random.randint(1, 1000)
    elif prop_type == PropType.BOOLEAN:
        value = random.choice([True, False])
    elif prop_type == PropType.DATETIME:
        value = datetime.now(UTC).isoformat()
    else:
        raise ValueError(f"Unknown property type: {prop_type}")

    return GeneratedProperty(key=key, value=value, prop_type=prop_type)


def mutate_property(prop: GeneratedProperty, event_number: int) -> None:
    """Mutate a property value in-place according to its type."""
    if prop.prop_type == PropType.STRING:
        prop.value = f"new_value_{event_number}"
    elif prop.prop_type == PropType.NUMBER:
        prop.value = prop.value + 1
    elif prop.prop_type == PropType.BOOLEAN:
        prop.value = not prop.value
    elif prop.prop_type == PropType.DATETIME:
        prop.value = datetime.now(UTC).isoformat()
    else:
        raise ValueError(f"Unknown property type: {prop.prop_type}")


def generate_person(seed_index: int) -> GeneratedPerson:
    """Generate a person with UUID distinct_id and random properties."""
    distinct_id = str(uuid.uuid4())

    # Generate 5 $set_once properties
    set_once_props = [generate_random_property("set_once_prop", i) for i in range(5)]

    # Generate 10 $set properties
    set_props = [generate_random_property("set_prop", i) for i in range(10)]

    return GeneratedPerson(
        distinct_id=distinct_id,
        set_once_props=set_once_props,
        set_props=set_props,
    )


class Command(BaseCommand):
    help = "Generate test persons and events with evolving person properties via capture_internal"

    def add_arguments(self, parser):
        parser.add_argument(
            "--team-id",
            type=int,
            required=True,
            help="Team ID to create events for",
        )
        parser.add_argument(
            "--num-persons",
            type=int,
            default=10,
            help="Number of persons to generate (default: 10)",
        )
        parser.add_argument(
            "--events-per-person",
            type=int,
            default=5,
            help="Number of $pageview events per person (default: 5)",
        )
        parser.add_argument(
            "--seed",
            type=int,
            help="Random seed for reproducibility",
        )

    def handle(self, *args, **options):
        team_id = options["team_id"]
        num_persons = options["num_persons"]
        events_per_person = options["events_per_person"]
        seed = options.get("seed")

        if seed is not None:
            random.seed(seed)

        # Look up team and get API token
        try:
            team = Team.objects.get(pk=team_id)
        except Team.DoesNotExist:
            self.stderr.write(self.style.ERROR(f"Team with ID {team_id} does not exist!"))
            return

        token = team.api_token
        self.stdout.write(f"Generating events for team '{team.name}' (ID: {team_id})")
        self.stdout.write(f"  Persons: {num_persons}")
        self.stdout.write(f"  Events per person: {events_per_person}")

        # Generate all persons up front
        self.stdout.write("Generating persons...")
        persons = [generate_person(i) for i in range(num_persons)]

        # Send $identify events for all persons
        self.stdout.write("Sending $identify events...")
        identify_failures = 0
        for i, person in enumerate(persons):
            identify_properties = {
                "$set_once": person.get_set_once_dict(),
                "$set": person.get_set_dict(),
            }

            try:
                resp = capture_internal(
                    token=token,
                    event_name="$identify",
                    event_source="generate_test_events",
                    distinct_id=person.distinct_id,
                    timestamp=datetime.now(UTC),
                    properties=identify_properties,
                    process_person_profile=True,
                )
                resp.raise_for_status()
            except Exception as e:
                identify_failures += 1
                logger.warning("identify_event_failed", distinct_id=person.distinct_id, error=str(e))

            if (i + 1) % 10 == 0:
                self.stdout.write(f"  Sent {i + 1}/{num_persons} $identify events...")

        self.stdout.write(self.style.SUCCESS(f"Sent {num_persons - identify_failures}/{num_persons} $identify events"))

        # Send $pageview events for each person
        self.stdout.write("Sending $pageview events...")
        pageview_count = 0
        pageview_failures = 0

        for person_idx, person in enumerate(persons):
            for event_num in range(1, events_per_person + 1):
                # Mutate all properties before each event
                for prop in person.set_props:
                    mutate_property(prop, event_num)
                for prop in person.set_once_props:
                    mutate_property(prop, event_num)

                pageview_properties: dict[str, Any] = {
                    "$current_url": f"https://example.com/page/{event_num}",
                    "$pathname": f"/page/{event_num}",
                    "$set_once": person.get_set_once_dict(),
                    "$set": person.get_set_dict(),
                }

                try:
                    resp = capture_internal(
                        token=token,
                        event_name="$pageview",
                        event_source="generate_test_events",
                        distinct_id=person.distinct_id,
                        timestamp=datetime.now(UTC),
                        properties=pageview_properties,
                        process_person_profile=True,
                    )
                    resp.raise_for_status()
                    pageview_count += 1
                except Exception as e:
                    pageview_failures += 1
                    logger.warning(
                        "pageview_event_failed",
                        distinct_id=person.distinct_id,
                        event_num=event_num,
                        error=str(e),
                    )

            if (person_idx + 1) % 10 == 0:
                self.stdout.write(
                    f"  Processed {person_idx + 1}/{num_persons} persons ({pageview_count} $pageview events)..."
                )

        total_events = num_persons + pageview_count
        total_failures = identify_failures + pageview_failures

        self.stdout.write(
            self.style.SUCCESS(
                f"Done! Sent {total_events} events ({num_persons} $identify + {pageview_count} $pageview), "
                f"{total_failures} failures"
            )
        )
