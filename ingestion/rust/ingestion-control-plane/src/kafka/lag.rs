use std::collections::HashMap;
use std::sync::Arc;
use std::time::Duration;

use anyhow::{anyhow, Context};
use futures::stream::{self, StreamExt};
use rdkafka::consumer::{BaseConsumer, Consumer};
use rdkafka::{Offset, TopicPartitionList};
use serde::Serialize;

use crate::config::Config;
use crate::kafka::client;

/// A consumer group and one topic it consumes, discovered from the cluster
/// by prefix: topics and groups matching the configured prefixes, associated
/// wherever the group has committed offsets on the topic.
#[derive(Debug, Clone, PartialEq, Eq, Serialize)]
pub struct ConsumerTarget {
    pub group: String,
    pub topic: String,
}

/// Discover consumer targets from the cluster. Runs one metadata request,
/// one group-list request, and one OffsetFetch per matching group (bounded
/// concurrency), all on the blocking pool.
pub async fn discover_targets(config: &Config) -> anyhow::Result<Vec<ConsumerTarget>> {
    let timeout = Duration::from_millis(config.kafka_metadata_timeout_ms);

    let (topics, groups) = {
        let config = config.clone();
        tokio::task::spawn_blocking(move || fetch_prefixed_topics_and_groups(&config, timeout))
            .await
            .context("discovery task panicked")??
    };

    let topics = Arc::new(topics);
    let mut targets: Vec<ConsumerTarget> = stream::iter(groups)
        .map(|group| {
            let config = config.clone();
            let topics = Arc::clone(&topics);
            async move {
                tokio::task::spawn_blocking(move || {
                    fetch_group_topics(&config, &group, &topics, timeout)
                })
                .await
                .context("group association task panicked")?
            }
        })
        .buffer_unordered(8)
        .collect::<Vec<_>>()
        .await
        .into_iter()
        .collect::<anyhow::Result<Vec<_>>>()?
        .into_iter()
        .flatten()
        .collect();

    targets.sort_by(|a, b| a.group.cmp(&b.group).then(a.topic.cmp(&b.topic)));
    Ok(targets)
}

type TopicsWithPartitions = Vec<(String, Vec<i32>)>;

fn fetch_prefixed_topics_and_groups(
    config: &Config,
    timeout: Duration,
) -> anyhow::Result<(TopicsWithPartitions, Vec<String>)> {
    let consumer = client::metadata_consumer(config).context("create metadata client")?;
    let metadata = consumer
        .fetch_metadata(None, timeout)
        .context("fetch cluster metadata")?;
    let topics: TopicsWithPartitions = metadata
        .topics()
        .iter()
        .filter(|t| t.name().starts_with(&config.topic_prefix))
        .map(|t| {
            (
                t.name().to_string(),
                t.partitions().iter().map(|p| p.id()).collect(),
            )
        })
        .collect();

    let group_list = consumer
        .fetch_group_list(None, timeout)
        .context("fetch consumer group list")?;
    let groups: Vec<String> = group_list
        .groups()
        .iter()
        .map(|g| g.name().to_string())
        .filter(|name| name.starts_with(&config.group_prefix) && name != client::INSPECTOR_GROUP_ID)
        .collect();

    Ok((topics, groups))
}

/// A group's topics are those it has committed offsets on, read with a
/// single OffsetFetch spanning every candidate partition.
fn fetch_group_topics(
    config: &Config,
    group: &str,
    topics: &TopicsWithPartitions,
    timeout: Duration,
) -> anyhow::Result<Vec<ConsumerTarget>> {
    let consumer = client::group_offsets_consumer(config, group).context("create group client")?;
    let mut tpl = TopicPartitionList::new();
    for (topic, partitions) in topics {
        for partition in partitions {
            tpl.add_partition(topic, *partition);
        }
    }
    let committed = consumer
        .committed_offsets(tpl, timeout)
        .with_context(|| format!("fetch committed offsets for group '{group}'"))?;

    let mut group_topics: Vec<String> = committed
        .elements()
        .iter()
        .filter(|elem| matches!(elem.offset(), Offset::Offset(_)))
        .map(|elem| elem.topic().to_string())
        .collect();
    group_topics.sort();
    group_topics.dedup();

    Ok(group_topics
        .into_iter()
        .map(|topic| ConsumerTarget {
            group: group.to_string(),
            topic,
        })
        .collect())
}

#[derive(Debug, Clone, Serialize)]
pub struct PartitionLag {
    pub partition: i32,
    pub low_watermark: i64,
    pub high_watermark: i64,
    pub committed_offset: Option<i64>,
    pub lag: i64,
}

#[derive(Debug, Serialize)]
pub struct GroupLag {
    pub group: String,
    pub topic: String,
    pub fetched_at: String,
    pub partitions: Vec<PartitionLag>,
}

/// Remaining messages for the group on one partition.
///
/// A committed offset below the low watermark means retention already deleted
/// messages past it, so only `high - low` messages are actually fetchable; a
/// committed offset above the high watermark (possible when reading the two
/// values non-atomically) clamps to zero. Without any commit, the whole
/// retained range is outstanding.
pub fn compute_lag(low: i64, high: i64, committed: Option<i64>) -> i64 {
    match committed {
        Some(c) => high - c.clamp(low, high),
        None => high - low,
    }
}

/// Scan committed offsets and watermarks for every partition of the target
/// group's topic. All rdkafka metadata calls are synchronous and run on the
/// blocking pool.
pub async fn scan_group_lag(config: &Config, target: &ConsumerTarget) -> anyhow::Result<GroupLag> {
    let timeout = Duration::from_millis(config.kafka_metadata_timeout_ms);
    let fetched_at = chrono::Utc::now().to_rfc3339();

    let (partitions, committed, consumer) = {
        let config = config.clone();
        let target = target.clone();
        tokio::task::spawn_blocking(move || {
            fetch_partitions_and_committed(&config, &target, timeout)
        })
        .await
        .context("offset scan task panicked")??
    };

    let consumer = Arc::new(consumer);
    let topic = target.topic.clone();
    let mut partition_lags: Vec<PartitionLag> = stream::iter(partitions)
        .map(|partition| {
            let consumer = Arc::clone(&consumer);
            let topic = topic.clone();
            async move {
                tokio::task::spawn_blocking(move || {
                    consumer
                        .fetch_watermarks(&topic, partition, timeout)
                        .map(|(low, high)| (partition, low, high))
                        .with_context(|| format!("fetch watermarks for partition {partition}"))
                })
                .await
                .context("watermark task panicked")?
            }
        })
        .buffer_unordered(16)
        .collect::<Vec<_>>()
        .await
        .into_iter()
        .map(|res| {
            res.map(|(partition, low, high)| {
                let committed_offset = committed.get(&partition).copied().flatten();
                PartitionLag {
                    partition,
                    low_watermark: low,
                    high_watermark: high,
                    committed_offset,
                    lag: compute_lag(low, high, committed_offset),
                }
            })
        })
        .collect::<anyhow::Result<_>>()?;

    partition_lags.sort_by(|a, b| b.lag.cmp(&a.lag).then(a.partition.cmp(&b.partition)));

    Ok(GroupLag {
        group: target.group.clone(),
        topic: target.topic.clone(),
        fetched_at,
        partitions: partition_lags,
    })
}

/// One row of the all-groups overview: total outstanding messages per
/// configured consumer target. Scan failures are reported inline so one
/// broken topic doesn't blank the whole overview.
#[derive(Debug, Clone, Serialize)]
pub struct GroupLagSummary {
    pub group: String,
    pub topic: String,
    pub partitions: usize,
    pub lagging_partitions: usize,
    pub total_lag: i64,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub error: Option<String>,
}

/// Scan every configured target concurrently, sorted by total lag desc.
/// The full overview, cached by the API layer; `fetched_at` tells the UI how
/// stale the cached scan is.
#[derive(Debug, Clone, Serialize)]
pub struct LagOverview {
    pub fetched_at: String,
    pub groups: Vec<GroupLagSummary>,
}

pub async fn scan_targets(config: &Config, targets: Vec<ConsumerTarget>) -> LagOverview {
    let fetched_at = chrono::Utc::now().to_rfc3339();
    let summaries = futures::future::join_all(targets.into_iter().map(|target| async {
        match scan_group_lag(config, &target).await {
            Ok(group_lag) => GroupLagSummary {
                group: target.group,
                topic: target.topic,
                partitions: group_lag.partitions.len(),
                lagging_partitions: group_lag.partitions.iter().filter(|p| p.lag > 0).count(),
                total_lag: group_lag.partitions.iter().map(|p| p.lag).sum(),
                error: None,
            },
            Err(e) => GroupLagSummary {
                group: target.group,
                topic: target.topic,
                partitions: 0,
                lagging_partitions: 0,
                total_lag: 0,
                error: Some(format!("{e:#}")),
            },
        }
    }))
    .await;

    let mut summaries = summaries;
    summaries.sort_by(|a, b| b.total_lag.cmp(&a.total_lag).then(a.group.cmp(&b.group)));
    LagOverview {
        fetched_at,
        groups: summaries,
    }
}

/// Watermarks and committed offset for a single partition, read at analysis
/// submit time. Synchronous — run on the blocking pool.
#[derive(Debug, Clone, Copy)]
pub struct PartitionBounds {
    pub low_watermark: i64,
    pub high_watermark: i64,
    pub committed_offset: Option<i64>,
}

pub fn fetch_partition_bounds_blocking(
    config: &Config,
    target: &ConsumerTarget,
    partition: i32,
    timeout: Duration,
) -> anyhow::Result<PartitionBounds> {
    let metadata_consumer = client::metadata_consumer(config).context("create metadata client")?;
    let (low_watermark, high_watermark) = metadata_consumer
        .fetch_watermarks(&target.topic, partition, timeout)
        .with_context(|| {
            format!(
                "fetch watermarks for '{}' partition {partition}",
                target.topic
            )
        })?;

    let group_consumer =
        client::group_offsets_consumer(config, &target.group).context("create group client")?;
    let mut tpl = TopicPartitionList::new();
    tpl.add_partition(&target.topic, partition);
    let committed_tpl = group_consumer
        .committed_offsets(tpl, timeout)
        .with_context(|| format!("fetch committed offset for group '{}'", target.group))?;
    let committed_offset = committed_tpl
        .find_partition(&target.topic, partition)
        .and_then(|elem| match elem.offset() {
            Offset::Offset(o) => Some(o),
            _ => None,
        });

    Ok(PartitionBounds {
        low_watermark,
        high_watermark,
        committed_offset,
    })
}

type PartitionsAndCommitted = (Vec<i32>, HashMap<i32, Option<i64>>, BaseConsumer);

fn fetch_partitions_and_committed(
    config: &Config,
    target: &ConsumerTarget,
    timeout: Duration,
) -> anyhow::Result<PartitionsAndCommitted> {
    let metadata_consumer = client::metadata_consumer(config).context("create metadata client")?;
    let metadata = metadata_consumer
        .fetch_metadata(Some(&target.topic), timeout)
        .with_context(|| format!("fetch metadata for topic '{}'", target.topic))?;
    let topic_metadata = metadata
        .topics()
        .iter()
        .find(|t| t.name() == target.topic)
        .ok_or_else(|| anyhow!("topic '{}' not found", target.topic))?;
    if let Some(err) = topic_metadata.error() {
        return Err(anyhow!(
            "broker returned error for topic '{}': {err:?}",
            target.topic
        ));
    }
    let partitions: Vec<i32> = topic_metadata.partitions().iter().map(|p| p.id()).collect();
    if partitions.is_empty() {
        return Err(anyhow!("topic '{}' has no partitions", target.topic));
    }

    let group_consumer =
        client::group_offsets_consumer(config, &target.group).context("create group client")?;
    let mut tpl = TopicPartitionList::new();
    for partition in &partitions {
        tpl.add_partition(&target.topic, *partition);
    }
    let committed_tpl = group_consumer
        .committed_offsets(tpl, timeout)
        .with_context(|| format!("fetch committed offsets for group '{}'", target.group))?;

    let committed: HashMap<i32, Option<i64>> = committed_tpl
        .elements()
        .iter()
        .map(|elem| {
            let offset = match elem.offset() {
                Offset::Offset(o) => Some(o),
                _ => None,
            };
            (elem.partition(), offset)
        })
        .collect();

    Ok((partitions, committed, metadata_consumer))
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn lag_is_high_minus_committed() {
        assert_eq!(compute_lag(0, 100, Some(40)), 60);
    }

    #[test]
    fn no_commit_means_whole_retained_range() {
        assert_eq!(compute_lag(10, 100, None), 90);
    }

    #[test]
    fn committed_below_low_watermark_clamps_to_retained_range() {
        assert_eq!(compute_lag(50, 100, Some(10)), 50);
    }

    #[test]
    fn committed_above_high_watermark_clamps_to_zero() {
        assert_eq!(compute_lag(0, 100, Some(120)), 0);
    }
}
