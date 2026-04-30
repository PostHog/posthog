#!/usr/bin/env python
"""Seed LLM analytics cluster data locally for UI testing.

Bypasses the full Temporal clustering pipeline (embeddings → UMAP → HDBSCAN → labeling)
by writing a synthetic `$ai_generation_clusters` event plus the `$ai_generation` and
`$ai_generation_summary` events the cluster detail UI reads from. The result is browsable
at `/llm-analytics/clusters/<run_id>/<cluster_id>` and is enough to exercise the cohort /
property filter bar end-to-end.

Usage:
    bin/seed-llm-clusters.py [--team-id 1] [--total 30] [--clusters 3]

Notes:
    - Persons are generated with two distinguishing fields so you can filter on them in
      the UI: `email` ('alice@example.com', 'bob@external.test', ...) and `country` ('US' / 'UK').
    - Generations are split evenly across persons and clusters.
    - The clustering window is the last 24 hours; the run id encodes the current date so
      the URL works regardless of when you run the script.
"""

from __future__ import annotations

import os
import sys
import uuid
import random
import argparse
from datetime import UTC, datetime, timedelta

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "posthog.settings")

import django

django.setup()

from posthog.models import Team  # noqa: E402
from posthog.models.event.util import create_event  # noqa: E402
from posthog.models.person.util import create_person, create_person_distinct_id  # noqa: E402

PERSON_TEMPLATES = [
    {"email": "alice@example.com", "country": "US"},
    {"email": "bob@external.test", "country": "UK"},
    {"email": "carol@example.com", "country": "US"},
    {"email": "dave@external.test", "country": "UK"},
    {"email": "erin@example.com", "country": "US"},
]

CLUSTER_TITLES = [
    "Customer support questions",
    "Code generation requests",
    "Summarization tasks",
    "Documentation lookups",
    "Translation queries",
]


def _ensure_persons(team: Team) -> dict[str, str]:
    """Create one ClickHouse person per template, plus a distinct_id mapping.

    Returns: email → person_uuid lookup so emitted generations can link to the person.
    Person rows are required for the property-values autocomplete (`/api/person/values?key=email`)
    to surface suggestions; the underlying SQL queries the `persons` ClickHouse table directly,
    not the events table, so person_properties on events alone aren't enough.
    """
    person_uuid_by_email: dict[str, str] = {}
    for person in PERSON_TEMPLATES:
        person_uuid = str(uuid.uuid4())
        create_person(
            team_id=team.id,
            version=0,
            uuid=person_uuid,
            properties=person,
            is_identified=True,
        )
        create_person_distinct_id(
            team_id=team.id,
            distinct_id=person["email"],
            person_id=person_uuid,
        )
        person_uuid_by_email[person["email"]] = person_uuid
    return person_uuid_by_email


def _emit_generation(
    *, team: Team, person: dict, person_uuid: str, trace_id: str, generation_id: str, ts: datetime
) -> None:
    create_event(
        event_uuid=uuid.uuid4(),
        event="$ai_generation",
        team=team,
        distinct_id=person["email"],
        timestamp=ts,
        properties={
            "$ai_trace_id": trace_id,
            "$ai_generation_id": generation_id,
            "$ai_model": "gpt-4o-mini",
            "$ai_input_tokens": random.randint(50, 500),
            "$ai_output_tokens": random.randint(50, 500),
            "$ai_total_cost_usd": round(random.uniform(0.001, 0.05), 6),
            "$ai_latency": round(random.uniform(0.5, 4.0), 3),
            "$ai_is_error": "false",
        },
        person_id=uuid.UUID(person_uuid),
        person_properties=person,
    )


def _emit_generation_summary(*, team: Team, trace_id: str, generation_id: str, title: str, ts: datetime) -> None:
    create_event(
        event_uuid=uuid.uuid4(),
        event="$ai_generation_summary",
        team=team,
        distinct_id=f"summary_{generation_id}",
        timestamp=ts,
        properties={
            "$ai_trace_id": trace_id,
            "$ai_generation_id": generation_id,
            "$ai_summary_title": title,
            "$ai_summary_flow_diagram": "",
            "$ai_summary_bullets": "- Test bullet one\n- Test bullet two",
            "$ai_summary_interesting_notes": "",
        },
    )


def _build_cluster(*, cluster_id: int, title: str, items: list[dict]) -> dict:
    """Mirror the shape `clusterDetailLogic` expects from `$ai_clusters`."""
    return {
        "cluster_id": cluster_id,
        "size": len(items),
        "title": title,
        "description": f"- Synthetic cluster seeded for local testing\n- Contains {len(items)} generations",
        "traces": {
            item["generation_id"]: {
                "distance_to_centroid": round(random.uniform(0.05, 0.5), 4),
                "rank": idx,
                "x": round(random.uniform(-3, 3), 3),
                "y": round(random.uniform(-3, 3), 3),
                "timestamp": item["timestamp"],
                "trace_id": item["trace_id"],
                "generation_id": item["generation_id"],
            }
            for idx, item in enumerate(items)
        },
        "centroid": [0.0] * 100,
        "centroid_x": round(random.uniform(-2, 2), 3),
        "centroid_y": round(random.uniform(-2, 2), 3),
    }


def seed(team_id: int, total: int, num_clusters: int) -> None:
    team = Team.objects.get(id=team_id)
    now = datetime.now(UTC).replace(microsecond=0)
    window_start = now - timedelta(hours=24)
    window_end = now

    person_uuid_by_email = _ensure_persons(team)
    items_by_cluster: list[list[dict]] = [[] for _ in range(num_clusters)]

    for i in range(total):
        person = PERSON_TEMPLATES[i % len(PERSON_TEMPLATES)]
        person_uuid = person_uuid_by_email[person["email"]]
        trace_id = str(uuid.uuid4())
        generation_id = str(uuid.uuid4())
        ts = window_start + timedelta(seconds=random.randint(0, 24 * 60 * 60 - 1))
        title = f"{CLUSTER_TITLES[i % num_clusters]} #{i + 1}"

        _emit_generation(
            team=team,
            person=person,
            person_uuid=person_uuid,
            trace_id=trace_id,
            generation_id=generation_id,
            ts=ts,
        )
        _emit_generation_summary(team=team, trace_id=trace_id, generation_id=generation_id, title=title, ts=ts)

        items_by_cluster[i % num_clusters].append(
            {
                "trace_id": trace_id,
                "generation_id": generation_id,
                "timestamp": ts.isoformat().replace("+00:00", "Z"),
            }
        )

    clusters = [
        _build_cluster(cluster_id=cluster_id, title=CLUSTER_TITLES[cluster_id % len(CLUSTER_TITLES)], items=items)
        for cluster_id, items in enumerate(items_by_cluster)
        if items
    ]

    run_id = f"{team_id}_generation_{now.strftime('%Y%m%d_%H%M%S')}_{uuid.uuid4()}"
    create_event(
        event_uuid=uuid.uuid4(),
        event="$ai_generation_clusters",
        team=team,
        distinct_id=f"clustering_generation_{team_id}",
        timestamp=now,
        properties={
            "$ai_clustering_run_id": run_id,
            "$ai_clustering_level": "generation",
            "$ai_clustering_job_id": "",
            "$ai_clustering_job_name": "local-seed",
            "$ai_window_start": window_start.isoformat().replace("+00:00", "Z"),
            "$ai_window_end": window_end.isoformat().replace("+00:00", "Z"),
            "$ai_total_items_analyzed": total,
            "$ai_clusters": clusters,
        },
    )

    base_url = "http://localhost:8010"  # adjust for your dev port
    print()  # noqa: T201
    print(f"Seeded {total} generations across {len(clusters)} clusters for team {team_id}.")  # noqa: T201
    print(f"Clusters list:    {base_url}/project/{team_id}/llm-analytics/clusters/{run_id}")  # noqa: T201
    if clusters:
        print(  # noqa: T201
            f"First cluster:    {base_url}/project/{team_id}/llm-analytics/clusters/{run_id}/{clusters[0]['cluster_id']}"
        )
    print()  # noqa: T201
    print("Try filtering by:")  # noqa: T201
    print("  - Person property `email` icontains `@example.com` (matches Alice / Carol / Erin)")  # noqa: T201
    print("  - Person property `country` exact `UK`            (matches Bob / Dave)")  # noqa: T201


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--team-id", type=int, default=1, help="Team ID to seed against (default: 1)")
    parser.add_argument("--total", type=int, default=30, help="Total generations to create (default: 30)")
    parser.add_argument("--clusters", type=int, default=3, help="Number of clusters to split into (default: 3)")
    args = parser.parse_args()
    seed(team_id=args.team_id, total=args.total, num_clusters=args.clusters)
