import { Assignment, Message, TopicPartitionOffset } from 'node-rdkafka'

import { defaultConfig } from '../../config/config'
import { HealthCheckResult } from '../../types'
import { logger } from '../../utils/logger'
import { KafkaConsumer, KafkaConsumerConfig, RdKafkaConsumerConfig } from './consumer-v1'
import { KafkaConsumerV2 } from './consumer-v2'

// Re-exports for back-compat with code that imports header parsers from `kafka/consumer`.
// These utilities are not really part of the consumer class and could move out later.
export { parseEventHeaders, parseKafkaHeaders } from './consumer-v1'
export type { KafkaConsumerConfig, RdKafkaConsumerConfig } from './consumer-v1'
export type { PartitionLifecycleCallback } from './consumer-v2'

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
    assignments(): Assignment[]
    /**
     * v1: updates the loop-staleness watchdog timestamp consulted by `isHealthy()`.
     * v2: no-op — the consume loop drives heartbeats automatically.
     * Call sites that need watchdog liveness under v1 (e.g. long-running per-batch work)
     * should call this even on v2 instances; the v2 implementation is intentionally cheap.
     *
     * TODO: remove from interface once v1 is decommissioned and v2's auto-heartbeat is
     * the only path. The no-op on v2 exists solely for interface conformance.
     */
    heartbeat(): void
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
