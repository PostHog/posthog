use std::time::{Duration, Instant};

use anyhow::Context;
use common_types::CapturedEventHeaders;
use rdkafka::consumer::{BaseConsumer, Consumer};
use rdkafka::message::Message;
use rdkafka::{Offset, TopicPartitionList};
use serde::Serialize;
use tokio_util::sync::CancellationToken;

use crate::jobs::Progress;
use crate::kafka::analysis::Aggregator;

#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize)]
#[serde(rename_all = "snake_case")]
pub enum TruncatedReason {
    Deadline,
    ByteBudget,
    ReachedHwm,
    Canceled,
}

pub struct FetchParams {
    pub topic: String,
    pub partition: i32,
    pub start_offset: i64,
    /// Where to stop reading (already clamped to the high watermark).
    pub end_offset_exclusive: i64,
    /// `start_offset + requested message count`, before clamping; used to
    /// report `reached_hwm` truncation.
    pub requested_end_offset: i64,
    pub deadline: Duration,
    pub max_bytes: u64,
    pub poll_timeout: Duration,
}

pub struct FetchOutcome {
    pub aggregator: Aggregator,
    /// Next unread offset when the fetch stopped.
    pub next_offset: i64,
    pub truncated_reason: Option<TruncatedReason>,
    pub duration_ms: u64,
}

/// Read `[start_offset, end_offset_exclusive)` from one partition, feeding
/// header-only samples into an [`Aggregator`]. Payloads are dropped
/// immediately; only their length is recorded. Synchronous — run on the
/// blocking pool.
pub fn run_fetch(
    consumer: &BaseConsumer,
    params: &FetchParams,
    progress: &Progress,
    cancel: &CancellationToken,
) -> anyhow::Result<FetchOutcome> {
    let mut tpl = TopicPartitionList::new();
    tpl.add_partition_offset(
        &params.topic,
        params.partition,
        Offset::Offset(params.start_offset),
    )
    .context("build assignment")?;
    consumer.assign(&tpl).context("assign partition")?;

    let started = Instant::now();
    let mut aggregator = Aggregator::new();
    let mut next_offset = params.start_offset;
    let mut bytes_read: u64 = 0;
    let mut truncated_reason = None;

    while next_offset < params.end_offset_exclusive {
        if cancel.is_cancelled() {
            truncated_reason = Some(TruncatedReason::Canceled);
            break;
        }
        if started.elapsed() >= params.deadline {
            truncated_reason = Some(TruncatedReason::Deadline);
            break;
        }

        let Some(result) = consumer.poll(params.poll_timeout) else {
            continue;
        };
        let message = result.context("poll partition")?;
        // librdkafka prefetches; drop anything past the requested range.
        if message.offset() >= params.end_offset_exclusive {
            break;
        }

        let payload_size = message.payload_len() as u64;
        let headers = message
            .headers()
            .map(|h| CapturedEventHeaders::from(h.detach()));
        aggregator.record(headers.as_ref(), payload_size);

        next_offset = message.offset() + 1;
        bytes_read += payload_size;
        progress.record(next_offset, payload_size);

        if bytes_read >= params.max_bytes {
            truncated_reason = Some(TruncatedReason::ByteBudget);
            break;
        }
    }

    if truncated_reason.is_none() && params.end_offset_exclusive < params.requested_end_offset {
        truncated_reason = Some(TruncatedReason::ReachedHwm);
    }

    Ok(FetchOutcome {
        aggregator,
        next_offset,
        truncated_reason,
        duration_ms: started.elapsed().as_millis() as u64,
    })
}
