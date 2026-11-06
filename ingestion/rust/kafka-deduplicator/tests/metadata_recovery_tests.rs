//! Integration tests for metadata.json-based local store recovery.
//!
//! These tests verify the end-to-end flow where metadata.json acts as the source of
//! truth for partition state across pod restarts:
//!
//! 1. A running pod writes records and commits Kafka offsets (which updates metadata.json).
//! 2. On restart, the new pod reads metadata.json, finds it fresh, and restores the local
//!    RocksDB store directly — skipping S3 import entirely.
//!
//! No external infrastructure is required (no Kafka, no MinIO).

use std::time::Duration;

use tempfile::TempDir;

use kafka_deduplicator::checkpoint::CheckpointMetadata;
use kafka_deduplicator::kafka::offset_tracker::OffsetTracker;
use kafka_deduplicator::kafka::types::Partition;
use kafka_deduplicator::store::{TimestampKey, TimestampMetadata};
use kafka_deduplicator::test_utils::test_helpers::TestRawEventBuilder;
use kafka_deduplicator::test_utils::{create_test_store_manager, create_test_tracker};

const TOPIC: &str = "test-topic";
const PARTITION: i32 = 0;
const MAX_STALENESS: Duration = Duration::from_secs(7200);

/// Simulate a Kafka offset commit: after processing messages up to consumer_offset,
/// the consumer commits and update_metadata_for_partition is called fire-and-forget.
async fn simulate_commit(
    store_manager: &kafka_deduplicator::store_manager::StoreManager,
    consumer_offset: i64,
    producer_offset: i64,
) {
    store_manager
        .update_metadata_for_partition(TOPIC, PARTITION, consumer_offset, producer_offset)
        .await;
}

/// Test: metadata.json is written after simulated Kafka commits and reflects the latest offsets.
#[tokio::test]
async fn test_metadata_written_on_simulated_commit() {
    let base_dir = TempDir::new().unwrap();
    let sm = create_test_store_manager(base_dir.path().to_path_buf());

    // Create a store for the partition
    sm.get_or_create_for_rebalance(TOPIC, PARTITION)
        .await
        .unwrap();

    // Simulate first commit at offset 100
    simulate_commit(&sm, 100, 50).await;

    // metadata.json should now exist with correct offsets
    let store_path =
        kafka_deduplicator::utils::format_store_path(base_dir.path(), TOPIC, PARTITION);
    let metadata = CheckpointMetadata::load_from_dir(&store_path)
        .await
        .expect("metadata.json should exist after commit");

    assert_eq!(metadata.consumer_offset, 100);
    assert_eq!(metadata.producer_offset, 50);
    assert_eq!(metadata.topic, TOPIC);
    assert_eq!(metadata.partition, PARTITION);

    // Simulate a second commit advancing the offsets
    simulate_commit(&sm, 250, 120).await;

    let metadata = CheckpointMetadata::load_from_dir(&store_path)
        .await
        .unwrap();
    assert_eq!(metadata.consumer_offset, 250);
    assert_eq!(metadata.producer_offset, 120);
}

/// Test: full recovery cycle — write records, commit, restart, restore from local data.
///
/// Verifies that:
/// - metadata.json written during session 1 is readable in session 2
/// - The restored RocksDB contains the records written in session 1
/// - The offsets from metadata.json are correct for OffsetTracker seeding
#[tokio::test]
async fn test_local_recovery_after_simulated_restart() {
    let base_dir = TempDir::new().unwrap();
    let base_path = base_dir.path().to_path_buf();

    // ─── Session 1: running pod ───────────────────────────────────────────────

    let sm1 = create_test_store_manager(base_path.clone());

    // Assignment: pre-create store for partition
    let store = sm1
        .get_or_create_for_rebalance(TOPIC, PARTITION)
        .await
        .unwrap();

    // Process some events
    let events: Vec<_> = (0..5)
        .map(|i| {
            TestRawEventBuilder::new()
                .random_uuid()
                .distinct_id(&format!("user_{i}"))
                .event(&format!("event_{i}"))
                .current_timestamp()
                .build()
        })
        .collect();

    for event in &events {
        let key = TimestampKey::from(event);
        let meta = TimestampMetadata::new(event);
        store.put_timestamp_record(&key, &meta).unwrap();
    }

    // Kafka offset commit: consumer_offset=1000, producer_offset=500
    simulate_commit(&sm1, 1000, 500).await;

    // Drop store and manager to release RocksDB lock (simulates pod going down)
    drop(store);
    drop(sm1);

    // ─── Session 2: pod restarting ────────────────────────────────────────────

    let sm2 = create_test_store_manager(base_path.clone());

    // try_restore_local_store should find fresh metadata.json and return it
    let metadata = sm2
        .try_restore_local_store(TOPIC, PARTITION, MAX_STALENESS)
        .await
        .expect("should find fresh local metadata after restart");

    assert_eq!(metadata.consumer_offset, 1000);
    assert_eq!(metadata.producer_offset, 500);

    // Open the existing RocksDB from the partition directory
    let store_path = kafka_deduplicator::utils::format_store_path(&base_path, TOPIC, PARTITION);
    sm2.restore_imported_store(TOPIC, PARTITION, &store_path)
        .unwrap();

    // Verify all records written in session 1 are accessible
    let restored_store = sm2
        .get(TOPIC, PARTITION)
        .expect("store should be registered");
    for event in &events {
        let key = TimestampKey::from(event);
        let record = restored_store.get_timestamp_record(&key).unwrap();
        assert!(
            record.is_some(),
            "record for {} should survive restart",
            event.event
        );
    }

    // Verify OffsetTracker is seeded correctly from the restored metadata
    let tracker = OffsetTracker::new(create_test_tracker());
    let partition_key = Partition::new(TOPIC.to_string(), PARTITION);
    tracker.init_partition_from_metadata(
        &partition_key,
        metadata.consumer_offset,
        metadata.producer_offset,
    );

    assert_eq!(
        tracker.get_committed_offset(&partition_key),
        Some(1000),
        "committed offset should match metadata consumer_offset"
    );
    assert_eq!(
        tracker.get_producer_offset(&partition_key),
        Some(500),
        "producer offset should match metadata producer_offset"
    );
}

/// Test: stale metadata.json is not used for recovery — falls back gracefully.
///
/// Verifies that if the metadata.json is older than max_staleness, try_restore_local_store
/// returns None so the caller falls through to S3 import.
#[tokio::test]
async fn test_stale_metadata_not_used_for_recovery() {
    let base_dir = TempDir::new().unwrap();
    let sm = create_test_store_manager(base_dir.path().to_path_buf());

    sm.get_or_create_for_rebalance(TOPIC, PARTITION)
        .await
        .unwrap();
    simulate_commit(&sm, 1000, 500).await;

    // A max_staleness of zero means any existing metadata is always stale
    let result = sm
        .try_restore_local_store(TOPIC, PARTITION, Duration::ZERO)
        .await;

    assert!(
        result.is_none(),
        "stale metadata should not be returned for recovery"
    );
}
