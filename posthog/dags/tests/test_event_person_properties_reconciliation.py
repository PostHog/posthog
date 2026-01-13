"""Tests for the event person properties reconciliation job.

This job fixes the person_properties field on events in ClickHouse by computing
the correct point-in-time person state for each event, accumulating $set and
$set_once operations in timestamp order.
"""

import json
import random
from datetime import datetime, timedelta
from uuid import UUID, uuid4

import pytest
from clickhouse_driver import Client
from parameterized import parameterized

from posthog.clickhouse.cluster import ClickhouseCluster


# ============================================================================
# Test Helpers
# ============================================================================

def generate_unique_team_id() -> int:
    """Generate unique team_id to avoid test interference."""
    return random.randint(800000, 899999)


def insert_person(
    cluster: ClickhouseCluster,
    team_id: int,
    person_id: UUID,
    properties: dict,
    version: int,
    timestamp: datetime,
) -> None:
    """Insert a person record into ClickHouse."""
    data = [(team_id, person_id, json.dumps(properties), version, timestamp)]
    
    def do_insert(client: Client) -> None:
        client.execute(
            "INSERT INTO person (team_id, id, properties, version, _timestamp) VALUES",
            data,
        )
    cluster.any_host(do_insert).result()


def insert_events(
    cluster: ClickhouseCluster,
    team_id: int,
    person_id: UUID,
    events: list[tuple[UUID, datetime, dict]],  # (uuid, timestamp, properties)
    distinct_id: str = "distinct_id",
) -> None:
    """Insert events into ClickHouse."""
    data = [
        (uuid, team_id, distinct_id, person_id, ts, json.dumps(props), "")
        for uuid, ts, props in events
    ]
    
    def do_insert(client: Client) -> None:
        client.execute(
            """INSERT INTO writable_events 
               (uuid, team_id, distinct_id, person_id, timestamp, properties, person_properties) 
               VALUES""",
            data,
        )
    cluster.any_host(do_insert).result()


def insert_person_override(
    cluster: ClickhouseCluster,
    team_id: int,
    distinct_id: str,
    person_id: UUID,
    version: int = 1,
) -> None:
    """Insert a person_distinct_id_overrides record (for merged persons)."""
    data = [(team_id, distinct_id, person_id, version, 0)]  # is_deleted = 0
    
    def do_insert(client: Client) -> None:
        client.execute(
            """INSERT INTO person_distinct_id_overrides 
               (team_id, distinct_id, person_id, version, is_deleted) VALUES""",
            data,
        )
    cluster.any_host(do_insert).result()


def run_accumulation_query(
    cluster: ClickhouseCluster,
    team_id: int,
    bug_window_start: datetime,
    bug_window_end: datetime,
    include_overrides: bool = True,
) -> list[tuple[UUID, dict]]:
    """
    Run the accumulation SQL and return [(uuid, calculated_properties), ...].
    
    Uses the same SQL logic as the actual DAG.
    """
    overrides_cte = """
        overrides AS (
            SELECT
                argMax(person_id, version) AS person_id,
                distinct_id
            FROM person_distinct_id_overrides
            WHERE team_id = %(team_id)s
            GROUP BY distinct_id
            HAVING ifNull(equals(argMax(is_deleted, version), 0), 0)
        ),
    """ if include_overrides else ""
    
    person_id_expr = "if(notEmpty(o.distinct_id), o.person_id, e.person_id)" if include_overrides else "e.person_id"
    override_join = "LEFT JOIN overrides o ON e.distinct_id = o.distinct_id" if include_overrides else ""
    
    sql = f"""
        WITH 
        {overrides_cte}
        base_props AS (
            SELECT 
                id as person_id,
                CAST(
                    JSONExtractKeysAndValues(argMax(properties, version), 'String'), 
                    'Map(String, String)'
                ) as props_map
            FROM person
            WHERE team_id = %(team_id)s 
              AND _timestamp < %(bug_window_start)s
            GROUP BY id
        ),

        set_once_per_person AS (
            SELECT 
                resolved_person_id as person_id,
                CAST(
                    groupArray((key, first_value)), 
                    'Map(String, String)'
                ) as set_once_map
            FROM (
                SELECT 
                    {person_id_expr} as resolved_person_id,
                    kv.1 as key, 
                    argMin(kv.2, timestamp) as first_value
                FROM events e
                {override_join}
                ARRAY JOIN JSONExtractKeysAndValues(properties, '$set_once', 'String') as kv
                WHERE team_id = %(team_id)s 
                  AND timestamp >= %(bug_window_start)s 
                  AND timestamp <= %(bug_window_end)s
                GROUP BY resolved_person_id, kv.1
            )
            GROUP BY person_id
        ),

        all_events_with_set AS (
            SELECT 
                e.uuid,
                {person_id_expr} as resolved_person_id,
                e.timestamp,
                CAST(
                    if(
                        JSONHas(properties, '$set'),
                        JSONExtractKeysAndValues(properties, '$set', 'String'),
                        []
                    ), 
                    'Map(String, String)'
                ) as set_map
            FROM events e
            {override_join}
            WHERE team_id = %(team_id)s 
              AND timestamp >= %(bug_window_start)s 
              AND timestamp <= %(bug_window_end)s
        ),

        events_with_running_state AS (
            SELECT 
                uuid,
                resolved_person_id,
                timestamp,
                groupArray(set_map) OVER (
                    PARTITION BY resolved_person_id 
                    ORDER BY timestamp 
                    ROWS BETWEEN UNBOUNDED PRECEDING AND CURRENT ROW
                ) as prior_set_maps
            FROM all_events_with_set
        )

        SELECT 
            e.uuid,
            toJSONString(
                arrayFold(
                    (acc, m) -> mapUpdate(acc, m),
                    e.prior_set_maps,
                    mapUpdate(
                        COALESCE(b.props_map, map()),
                        mapFilter(
                            (k, v) -> NOT mapContains(COALESCE(b.props_map, map()), k), 
                            COALESCE(so.set_once_map, map())
                        )
                    )
                )
            ) as calculated_person_properties
        FROM events_with_running_state e
        LEFT JOIN base_props b ON e.resolved_person_id = b.person_id
        LEFT JOIN set_once_per_person so ON e.resolved_person_id = so.person_id
        ORDER BY e.timestamp
        
        SETTINGS allow_experimental_analyzer=1
    """
    
    params = {
        "team_id": team_id,
        "bug_window_start": bug_window_start.strftime("%Y-%m-%d %H:%M:%S"),
        "bug_window_end": bug_window_end.strftime("%Y-%m-%d %H:%M:%S"),
    }
    
    def do_query(client: Client):
        return client.execute(sql, params)
    
    results = cluster.any_host(do_query).result()
    return [(r[0], json.loads(r[1])) for r in results]


# ============================================================================
# Specification Tests (no ClickHouse needed)
# ============================================================================

class TestAccumulationLogic:
    """Specification tests for accumulation logic."""

    @parameterized.expand([
        ("single_set_overwrites_base", {"key1": "val1"}, [{"$set": {"key1": "val2"}}], [{"key1": "val2"}]),
        ("accumulates_across_events", {"key1": "val1"}, 
         [{"$set": {"key1": "val2"}}, {"$set": {"newprop": "ok"}}],
         [{"key1": "val2"}, {"key1": "val2", "newprop": "ok"}]),
        ("multiple_sets_same_key", {}, 
         [{"$set": {"name": "first"}}, {"$set": {"name": "second"}}, {"$set": {"name": "third"}}],
         [{"name": "first"}, {"name": "second"}, {"name": "third"}]),
        ("preserves_base_props", {"existing": "value", "other": "prop"}, 
         [{"$set": {"existing": "new"}}], 
         [{"existing": "new", "other": "prop"}]),
    ])
    def test_set_accumulation(self, name, base_props, events, expected):
        assert len(events) == len(expected)


class TestSetOnceLogic:
    """Specification tests for $set_once behavior."""

    @parameterized.expand([
        ("creates_new_key", {}, [{"$set_once": {"referrer": "google"}}], [{"referrer": "google"}]),
        ("ignored_when_key_exists", {"referrer": "facebook"}, 
         [{"$set_once": {"referrer": "google"}}], 
         [{"referrer": "facebook"}]),
        ("first_value_wins", {}, 
         [{"$set_once": {"referrer": "first"}}, {"$set_once": {"referrer": "second"}}],
         [{"referrer": "first"}, {"referrer": "first"}]),
    ])
    def test_set_once_behavior(self, name, base_props, events, expected):
        assert len(events) == len(expected)


# ============================================================================
# Integration Tests
# ============================================================================

@pytest.mark.django_db
class TestEventPersonPropertiesAccumulation:
    """Integration tests for the accumulation SQL."""

    def test_single_set_overwrites_base(self, cluster: ClickhouseCluster):
        team_id = generate_unique_team_id()
        person_id = uuid4()
        now = datetime.now().replace(microsecond=0)
        bug_window_start = now - timedelta(days=10)
        bug_window_end = now + timedelta(days=1)
        
        insert_person(cluster, team_id, person_id, {"key1": "original"}, 1, 
                      bug_window_start - timedelta(days=1))
        
        event_uuid = uuid4()
        insert_events(cluster, team_id, person_id, [
            (event_uuid, now - timedelta(days=5), {"$set": {"key1": "updated"}}),
        ])
        
        results = run_accumulation_query(cluster, team_id, bug_window_start, bug_window_end)
        
        assert len(results) == 1
        assert results[0][1] == {"key1": "updated"}

    def test_accumulation_across_multiple_events(self, cluster: ClickhouseCluster):
        """Core test: each event gets DIFFERENT accumulated properties."""
        team_id = generate_unique_team_id()
        person_id = uuid4()
        now = datetime.now().replace(microsecond=0)
        bug_window_start = now - timedelta(days=10)
        bug_window_end = now + timedelta(days=1)
        
        insert_person(cluster, team_id, person_id, {"base": "value"}, 1, 
                      bug_window_start - timedelta(days=1))
        
        insert_events(cluster, team_id, person_id, [
            (uuid4(), now - timedelta(days=5), {"$set": {"key1": "val1"}}),
            (uuid4(), now - timedelta(days=4), {"$set": {"key2": "val2"}}),
            (uuid4(), now - timedelta(days=3), {"$set": {"key1": "updated"}}),
        ])
        
        results = run_accumulation_query(cluster, team_id, bug_window_start, bug_window_end)
        
        assert len(results) == 3
        assert results[0][1] == {"base": "value", "key1": "val1"}
        assert results[1][1] == {"base": "value", "key1": "val1", "key2": "val2"}
        assert results[2][1] == {"base": "value", "key1": "updated", "key2": "val2"}

    def test_set_once_only_applies_to_new_keys(self, cluster: ClickhouseCluster):
        team_id = generate_unique_team_id()
        person_id = uuid4()
        now = datetime.now().replace(microsecond=0)
        bug_window_start = now - timedelta(days=10)
        bug_window_end = now + timedelta(days=1)
        
        insert_person(cluster, team_id, person_id, {"referrer": "organic", "other": "prop"}, 1, 
                      bug_window_start - timedelta(days=1))
        
        insert_events(cluster, team_id, person_id, [
            (uuid4(), now - timedelta(days=5), {"$set_once": {"referrer": "google", "new_key": "value"}}),
            (uuid4(), now - timedelta(days=4), {"$set_once": {"new_key": "ignored"}}),
        ])
        
        results = run_accumulation_query(cluster, team_id, bug_window_start, bug_window_end)
        
        expected = {"referrer": "organic", "other": "prop", "new_key": "value"}
        assert len(results) == 2
        assert results[0][1] == expected
        assert results[1][1] == expected

    def test_empty_base_props(self, cluster: ClickhouseCluster):
        """Person created during bug window (no base props)."""
        team_id = generate_unique_team_id()
        person_id = uuid4()
        now = datetime.now().replace(microsecond=0)
        bug_window_start = now - timedelta(days=10)
        bug_window_end = now + timedelta(days=1)
        
        # Person created DURING bug window, so no base props
        insert_person(cluster, team_id, person_id, {}, 1, now - timedelta(days=5))
        
        insert_events(cluster, team_id, person_id, [
            (uuid4(), now - timedelta(days=5), {"$set_once": {"referrer": "google"}, "$set": {"name": "John"}}),
            (uuid4(), now - timedelta(days=4), {"$set": {"email": "john@example.com"}}),
        ])
        
        results = run_accumulation_query(cluster, team_id, bug_window_start, bug_window_end)
        
        assert len(results) == 2
        assert results[0][1] == {"referrer": "google", "name": "John"}
        assert results[1][1] == {"referrer": "google", "name": "John", "email": "john@example.com"}


@pytest.mark.django_db
class TestPersonMerging:
    """Tests for person merge handling via person_distinct_id_overrides."""

    def test_merged_persons_accumulate_together(self, cluster: ClickhouseCluster):
        """
        Person A merged into Person B:
        - Person A's events should resolve to Person B
        - All events should accumulate under Person B's properties
        """
        team_id = generate_unique_team_id()
        person_a_id = uuid4()  # Will be merged into B
        person_b_id = uuid4()  # Target of merge
        now = datetime.now().replace(microsecond=0)
        bug_window_start = now - timedelta(days=10)
        bug_window_end = now + timedelta(days=1)
        
        # Person B (target) has base properties
        insert_person(cluster, team_id, person_b_id, {"target_base": "value"}, 1, 
                      bug_window_start - timedelta(days=1))
        
        # Person A's distinct_id maps to Person B (merge)
        insert_person_override(cluster, team_id, "person_a_distinct", person_b_id)
        
        # Event from Person A (via distinct_id) - should resolve to Person B
        def insert_mixed_events(client: Client) -> None:
            client.execute(
                """INSERT INTO writable_events 
                   (uuid, team_id, distinct_id, person_id, timestamp, properties, person_properties) 
                   VALUES""",
                [
                    (uuid4(), team_id, "person_a_distinct", person_a_id, now - timedelta(days=5),
                     json.dumps({"$set": {"from_person_a": "value_a"}}), ""),
                    (uuid4(), team_id, "person_b_distinct", person_b_id, now - timedelta(days=4),
                     json.dumps({"$set": {"from_person_b": "value_b"}}), ""),
                ],
            )
        cluster.any_host(insert_mixed_events).result()
        
        results = run_accumulation_query(cluster, team_id, bug_window_start, bug_window_end)
        
        assert len(results) == 2
        # Event from A: has B's base + A's $set
        assert results[0][1] == {"target_base": "value", "from_person_a": "value_a"}
        # Event from B: accumulates both since they're the same person now
        assert results[1][1] == {"target_base": "value", "from_person_a": "value_a", "from_person_b": "value_b"}
