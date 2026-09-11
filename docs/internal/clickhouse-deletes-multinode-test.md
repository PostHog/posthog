# Test adhoc event deletion across clusters

The opt-in test in `posthog/dags/tests/test_deletes_multinode.py` executes the complete `deletes_job` across two distinct ClickHouse clusters: a data cluster with one node and an events cluster with two shards.
It uses real ClickHouse discovery, S3 dictionary staging, asynchronous delete mutations, mutation waits, request completion, and cleanup.
It does not mock cluster routing or the deletion ops.

Both `events` and `events_json` start with the same four events.
Two `(team_id, uuid)` pairs are queued in `adhoc_events_deletion`, with one matching row on each events shard.
The two controls are an unqueued event and the same UUID as a queued event in another team.
The test compares the ordered event rows before and after the job, checks the exact remaining identities on each storage shard, checks the deletion markers, and checks the job's survivor counts.

## Run locally

Start the usual backend test dependencies first, including PostgreSQL, ZooKeeper on port 2181, and SeaweedFS on port 19000 with the configured object-storage bucket.
Use the repository's activated Python environment.
The existing Dagster pytest fixtures also require the `test_dagster` PostgreSQL database.

```bash
docker compose -f docker-compose.deletes-test.yml up -d --wait
TEST_MULTINODE_DELETES=1 hogli test posthog/dags/tests/test_deletes_multinode.py
```

The compose file uses host networking, so run it on Linux or Docker Desktop with host networking enabled.
It adds three ClickHouse servers on native ports 19101 through 19103, HTTP ports 18101 through 18103, and interserver ports 19201 through 19203.
The existing development ClickHouse service stays on its usual ports.
Do not run this test concurrently with another invocation of itself.
The test creates the configured ClickHouse test database on the dedicated nodes and drops it afterward; setup refuses an already-existing database.
The test is skipped unless `TEST_MULTINODE_DELETES=1` is set.

```bash
docker compose -f docker-compose.deletes-test.yml down -v
```

## Topology and assertions

| Cluster              | Nodes             | Event tables on each node            |
| -------------------- | ----------------- | ------------------------------------ |
| `delete_test_data`   | One data node     | `events`, `sharded_events`           |
| `delete_test_events` | Two events shards | `events_json`, `sharded_events_json` |

The test asserts the table placement on every node before inserting rows.
Neither JSON event table exists on the data node, and neither legacy event table exists on the events nodes.
Each events node's `events_json` Distributed table reads both events shards.
The test reads `events` from the data cluster and `events_json` from each events node, comparing identical input rows and exact survivors after the job.

The job's current verification tries to query `events_json` on the data cluster, where it does not exist in this topology.
That metadata count is `None`, meaning unknown.
The test asserts this limitation explicitly and independently verifies JSON event deletion through both events proxies and each physical shard.
The job's separate `sharded_events_json` storage count must also report zero surviving matches.

The separate-cluster case also exercises overlapping shard numbers: both the data cluster and the first events shard have shard number 1.
Both event storage tables and their Distributed proxies use the application's schema factories.
The row comparison covers team ID, event UUID, timestamp, event name, distinct ID, and person ID.
The test uses a unique S3 staging prefix and removes its staged objects afterward.
This is a deletion-routing test, not a migration or ingestion test.
It uses one replica per shard and a shared local ZooKeeper; replica lag and independent Keeper deployments are outside its coverage.
The events nodes do not have the source deletion table, so their dictionaries must load through S3.

A local reproduction identifies a possible failure mode, not the cause of a particular deployed run.
For that diagnosis, compare the deployed job version, the cluster configuration, the placement of `sharded_events_json`, and the run's `mark_deletions_verified` metadata.
The current job marks requests verified even when survivor counts are nonzero or unavailable.
