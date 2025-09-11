use std::{sync::Arc, time::Duration};

use app_context::AppContext;
use batch_ingestion::process_batch;
use common_kafka::kafka_consumer::{RecvErr, SingleTopicConsumer};
use config::Config;
use metrics_consts::{
    BATCH_ACQUIRE_TIME, CACHE_CONSUMED, COMPACTED_UPDATES, DUPLICATES_IN_BATCH, EMPTY_EVENTS,
    EVENTS_RECEIVED, EVENT_PARSE_ERROR, FORCED_SMALL_BATCH, RECV_DEQUEUED,
    SKIPPED_DUE_TO_TEAM_FILTER, UPDATES_FILTERED_BY_CACHE, UPDATES_PER_EVENT, UPDATES_SEEN,
    UPDATE_PRODUCER_OFFSET, WORKER_BLOCKED,
};
use types::{Event, Update};

use ahash::AHashSet;
use tokio::sync::mpsc::error::TrySendError;
use tracing::{error, warn};
use update_cache::Cache;

use crate::{
    measuring_channel::{MeasuringReceiver, MeasuringSender},
    metrics_consts::CHANNEL_MESSAGES_IN_FLIGHT,
};

pub mod api;
pub mod app_context;
pub mod batch_ingestion;
pub mod config;
pub mod measuring_channel;
pub mod metrics_consts;
pub mod types;
pub mod update_cache;

pub async fn update_consumer_loop(
    config: Config,
    cache: Arc<Cache>,
    context: Arc<AppContext>,
    mut channel: MeasuringReceiver<Update>,
) {
    loop {
        let mut batch = Vec::with_capacity(config.update_batch_size);

        let batch_start = tokio::time::Instant::now();
        let batch_time = common_metrics::timing_guard(BATCH_ACQUIRE_TIME, &[]);
        while batch.len() < config.update_batch_size {
            context.worker_liveness.report_healthy().await;

            metrics::gauge!(CHANNEL_MESSAGES_IN_FLIGHT)
                .set(channel.get_inflight_messages_count() as f64);

            let remaining_capacity = config.update_batch_size - batch.len();
            // We race these two, so we can escape this loop and do a small batch if we've been waiting too long
            let recv = channel.recv_many(&mut batch, remaining_capacity);
            let sleep = tokio::time::sleep(Duration::from_secs(1));

            tokio::select! {
                got = recv => {
                    if got == 0 {
                        // Indicates all workers have exited, so we should too
                        panic!("Coordinator recv failed, dying");
                    }
                    metrics::gauge!(RECV_DEQUEUED).set(got as f64);
                    continue;
                }
                _ = sleep => {
                    if batch_start.elapsed() > Duration::from_secs(config.max_issue_period) {
                        warn!("Forcing small batch due to time limit");
                        metrics::counter!(FORCED_SMALL_BATCH).increment(1);
                        break;
                    }
                }
            }
        }
        batch_time.fin();

        // We de-duplicate the batch, in case racing inserts slipped through the shared-cache filter. This
        // is important because duplicate updates touch the same row, and we issue in parallel, so we'd end
        // up deadlocking ourselves. We can still encounter deadlocks due to other pods, but those should
        // be rarer, and we use retries to handle them.
        let start_len = batch.len();
        batch.sort_unstable();
        batch.dedup();

        metrics::counter!(DUPLICATES_IN_BATCH).increment((start_len - batch.len()) as u64);

        // this should only be performed here, per *update batch* as it's
        // more expensive now that this is 3 per-def-type caches in a trenchcoat
        let cache_utilization = cache.len() as f64 / config.cache_capacity as f64;
        metrics::gauge!(CACHE_CONSUMED).set(cache_utilization);

        // enrich batch group events with resolved group_type_indices
        // before passing along to process_batch
        let _unused = context
            .resolve_group_types_indexes(&mut batch)
            .await
            .map_err(|e| {
                warn!(
                    "Failed resolving group type indices for batch, got: {:?}",
                    e
                )
            });

        process_batch(&config, cache.clone(), &context.pool, batch).await;
    }
}

pub async fn update_producer_loop(
    config: Config,
    consumer: SingleTopicConsumer,
    shared_cache: Arc<Cache>,
    channel: MeasuringSender<Update>,
) {
    let mut batch = AHashSet::with_capacity(config.compaction_batch_size);
    let mut last_send = tokio::time::Instant::now();
    loop {
        let (event, offset): (Event, _) = match consumer.json_recv().await {
            Ok(r) => r,
            Err(RecvErr::Empty) => {
                warn!("Received empty event");
                metrics::counter!(EMPTY_EVENTS).increment(1);
                continue;
            }
            Err(RecvErr::Serde(e)) => {
                metrics::counter!(EVENT_PARSE_ERROR).increment(1);
                warn!("Failed to parse event: {:?}", e);
                continue;
            }
            Err(RecvErr::Kafka(e)) => {
                panic!("Kafka error: {e:?}"); // We just panic if we fail to recv from kafka, if it's down, we're down
            }
        };

        // NOTE: we extended the autocommit interval in production envs to 20 seconds
        // as a temporary remediation for events already buffered in a pod's internal
        // queue being skipped when the consumer group rebalances or the service is
        // redeployed. Long-term fix: start tracking max partition offsets in the
        // Update batches and commit them only when each batch succeeds. This will
        // not be perfect, as batch writes are async and can complete out of order,
        // but is better than what we're doing right now
        let curr_offset = offset.get_value();
        match offset.store() {
            Ok(_) => (),
            Err(e) => {
                metrics::counter!(UPDATE_PRODUCER_OFFSET, &[("op", "store_fail")]).increment(1);
                // TODO: consumer json_recv() should expose the source partition ID too
                error!("update_producer_loop: failed to store offset {curr_offset}, got: {e}");
            }
        }

        if !config
            .filter_mode
            .should_process(&config.filtered_teams.teams, event.team_id)
        {
            metrics::counter!(SKIPPED_DUE_TO_TEAM_FILTER).increment(1);
            continue;
        }

        let updates = event.into_updates(config.update_count_skip_threshold);

        metrics::counter!(EVENTS_RECEIVED).increment(1);
        metrics::counter!(UPDATES_SEEN).increment(updates.len() as u64);
        metrics::histogram!(UPDATES_PER_EVENT).record(updates.len() as f64);

        for update in updates {
            if batch.contains(&update) {
                metrics::counter!(COMPACTED_UPDATES).increment(1);
                continue;
            }
            batch.insert(update);
        }

        // We do the full batch insert before checking the time/batch size, because if we did this
        // inside the for update in updates loop, under extremely low-load situations, we'd push a
        // single update into the channel, then push the rest into the batch, and loop around to
        // wait on the next event, which might come an arbitrary amount of time later. This bit me
        // in testing, and while it's not a correctness problem and under normal load we'd never
        // see it, we may as well just do the full batch insert first.
        if batch.len() >= config.compaction_batch_size
            || last_send.elapsed() > Duration::from_secs(10)
        {
            last_send = tokio::time::Instant::now();
            for update in batch.drain() {
                if shared_cache.contains_key(&update) {
                    // the above can replace this metric when we have new hit/miss stats both flowing
                    metrics::counter!(UPDATES_FILTERED_BY_CACHE).increment(1);
                    continue;
                }

                // TEMPORARY: both old (v1) and new (v2) write paths will utilize the old
                // not-great caching strategy for now: optimistically add entries before
                // they are safely persisted to Postgres, and painfully extract them
                // when batch writes fail. This may be a fine trade for now, since
                // v2 batch writes fail much less often than v1
                shared_cache.insert(update.clone());

                match channel.try_send(update) {
                    Ok(_) => {}
                    Err(TrySendError::Full(update)) => {
                        warn!("Worker blocked");
                        metrics::counter!(WORKER_BLOCKED).increment(1);
                        // Workers should just die if the channel is dropped, since that indicates
                        // the main loop is dead.
                        channel.send(update).await.unwrap();
                    }
                    Err(e) => {
                        warn!("Coordinator send failed: {:?}", e);
                        return;
                    }
                }
            }
        }
    }
}
