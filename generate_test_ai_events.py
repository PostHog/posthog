#!/usr/bin/env python
"""Generate test AI events for LLMA metrics testing."""
# ruff: noqa: T201, E402

import os
import sys
import uuid
from datetime import datetime, timedelta

# Setup Django
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "posthog.settings")
sys.path.insert(0, os.path.dirname(__file__))

import django

django.setup()

from posthog.models import Team
from posthog.models.event.util import create_event


def generate_test_events():
    """Generate test AI events for yesterday."""
    print("Generating test AI events for yesterday...")

    # Get first available team
    team = Team.objects.first()
    if not team:
        print("❌ No teams found. Please create a team first.")
        return
    print(f"Using Team {team.id}: {team.name}")

    # Generate events for yesterday
    yesterday = datetime.now() - timedelta(days=1)

    # Insert various AI event types with some error events
    # Format: (event_type, total_count, error_count)
    events_to_create = [
        ("$ai_trace", 15, 2),  # ~13% error rate
        ("$ai_generation", 8, 1),  # ~13% error rate
        ("$ai_span", 25, 5),  # 20% error rate
        ("$ai_embedding", 5, 0),  # 0% error rate
    ]

    total = 0
    total_errors = 0
    for event_type, count, error_count in events_to_create:
        for i in range(count):
            # First error_count events will have errors
            properties = {}
            if i < error_count:
                properties["$ai_is_error"] = True
                properties["$ai_error"] = f"Test error {i} for {event_type}"

            create_event(
                event_uuid=uuid.uuid4(),
                event=event_type,
                team=team,
                distinct_id=f"test_user_{i}",
                timestamp=yesterday,
                properties=properties,
            )
        total += count
        total_errors += error_count
        print(f"  ✓ Inserted {count:2d} {event_type} events ({error_count} with errors)")

    print(f"\n✓ Total: {total} test AI events inserted for {yesterday.date()}")
    print(f"✓ Total errors: {total_errors} ({total_errors * 100.0 / total:.1f}% overall error rate)")


if __name__ == "__main__":
    generate_test_events()
