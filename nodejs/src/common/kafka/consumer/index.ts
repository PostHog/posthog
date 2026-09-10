import { Message, PartitionMetadata, TopicPartitionOffset } from 'node-rdkafka'

import { HealthCheckResult } from '~/types'

import { defaultConfig } from '../../config/config'
import { logger } from '../../utils/logger'
import { KafkaConsumer, KafkaConsumerConfig, RdKafkaConsumerConfig } from './consumer-v1'
import { KafkaConsumerV2 } from './consumer-v2'

// Re-exports for back-compat with code that imports header parsers from `kafka/consumer`.
// These utilities are not really part of the consumer class and could move out later.
export { parseEventHeaders, parseKafkaHeaders } from './consumer-v1'
export type { KafkaConsumerConfig, RdKafkaConsumerConfig } from './consumer-v1'

/**
 * Overrides `auto.offset.reset` so a fresh consumer group starts at the tip of the topic instead
 * of replaying the retained backlog. `auto.offset.reset` is a topic-level librdkafka property, so
 * the global config type has no slot for it; both implementations mirror the value into the
 * explicit topic config, which is the form librdkafka honors (see node-rdkafka #984).
 */
export const START_AT_LATEST = { ['auto.offset.reset' as keyof RdKafkaConsumerConfig]: 'latest' as never }

/**
 * The shared surface that both KafkaConsumer (v1) and KafkaConsumerV2 expose to call sites.
 * Keep this small — every method here pins the migration. Adding a method here forces both
 * implementations to support it.
 */
export interface KafkaConsumerInterface {
    connect(eachBatch: (messages: Message[]) => Promise<{ backgroundTask?: Promise<unknown> } | void>): Promise<void>
    disconnect(): Promise<void>
    isHealthy(): HealthCheckResult
    offsetsStore(offsets: TopicPartitionOffset[]): void
    /** Broker-side `[low, high]` offsets for a partition. `high` is the next offset to be produced. */
    queryWatermarkOffsets(topic: string, partition: number, timeout?: number): Promise<[number, number]>
    /** The group's committed offsets for the currently assigned partitions. */
    committedOffsets(timeout?: number): Promise<TopicPartitionOffset[]>
    /** Broker-reported partitions of a topic, whether or not this consumer is assigned them. */
    getPartitionsForTopic(topic: string): Promise<PartitionMetadata[]>
}

/**
 * Single entry-point for instantiating a Kafka consumer. v1/v2 selection is driven by the
 * `CONSUMER_USE_V2` env var (boolean, applies to the entire service). Call sites should
 * never `new KafkaConsumer(...)` directly during the rollout — go through this factory.
 */
export function createKafkaConsumer(
    config: KafkaConsumerConfig,
    rdKafkaConfig: RdKafkaConsumerConfig = {}
): KafkaConsumerInterface {
    if (defaultConfig.CONSUMER_USE_V2) {
        logger.info('🔁', 'kafka_consumer_factory_using_v2', { groupId: config.groupId, topic: config.topic })
        return new KafkaConsumerV2(config, rdKafkaConfig)
    }
    return new KafkaConsumer(config, rdKafkaConfig)
}
