/**
 * - A note on Kafka partitioning
 *
 * We are ingesting events and partitioning based on session_id. This means that we can have multiple sessions
 * going to one partition, but for any given ID they should land all on the same partition.
 *
 * As we want to buffer events before writing them to S3, we don't auto-commit our kafka consumer offsets.
 * Instead, we track all offsets that are "in-flight" and when we flush a buffer to S3 we remove these in-flight offsets
 * and write the oldest offset to Kafka. This allows us to resume from the oldest offset in the case of a consumer
 * restart or rebalance, even if some of the following offsets have already been written to S3.
 *
 * The other trick is when a rebalance occurs we need to remove all in-flight sessions for partitions that are no longer
 * assigned to us.
 *
 * This all works based on the idea that there is only one consumer (Orchestrator) per partition, allowing us to
 * track everything in this single process
 *
 * The expected lifecycle for a partition on the offset manager is
 *
 * 1. `assignPartition` - called when a partition is assigned to this consumer
 *      - it doesn't actually matter that this is called first,
 *      as it only checks if the manager is already tracking the partition as revoked
 * 2. `addOffset` - called when a message is received from Kafka
 *      - it should be impossible for a consumer to process a message without first adding it here
 * 3. `removeOffset`
 *      - called when a message is written to S3
 *      if it is called for a partition that is not being tracked and has not been revoked then something is wrong in a weird way
 * 4. `revokePartition`
 *      - called when a partition is revoked from this consumer
 * 5. `removeOffset`
 *      - this could be called after revoke if we were processing messages for that partition as it was revoked
 *      these messages can be safely ignored
 *
 *
 */

import { captureException } from '@sentry/node'
import { KafkaConsumer } from 'node-rdkafka-acosom'
import { Gauge } from 'prom-client'

import { status } from '../../../../utils/status'

export const gaugeOffsetCommitted = new Gauge({
    name: 'offset_manager_offset_committed',
    help: 'When a session manager flushes to S3 it reports which offset on the partition it flushed.',
})

export const gaugeOffsetRemovalImpossible = new Gauge({
    name: 'offset_manager_offset_removal_impossible',
    help: 'When a session manager flushes to S3 it reports which offset on the partition it flushed. That should always match an offset being managed',
    labelNames: ['partition'],
})

export const gaugeOffsetRemovalAfterRevoke = new Gauge({
    name: 'offset_manager_offset_removal_after_revoke',
    help: 'When a session manager flushes to S3 it reports which offset on the partition it flushed. This could come after a rebalance, so we track that here',
    labelNames: ['partition'],
})

interface SessionOffset {
    session_id: string
    offset: number
}

export class OffsetManager {
    // We have to track every message's offset so that we can commit them only after they've been written to S3
    // as we add them we keep track of the session id so that if an ingester gets blocked
    // we can track that back to the session id for debugging
    offsetsByPartitionTopic: Map<string, SessionOffset[]> = new Map()
    // when a rebalance occurs we may have ongoing processing that subsequently calls into the offset manager
    // we want to know when this happens as it is safe to ignore
    revokedPartitions: Record<string, Set<number>> = {}

    constructor(private consumer: KafkaConsumer) {}

    public addOffset(topic: string, partition: number, session_id: string, offset: number): void {
        const key = `${topic}-${partition}`

        if (!this.offsetsByPartitionTopic.has(key)) {
            this.offsetsByPartitionTopic.set(key, [])
        }

        const current = this.offsetsByPartitionTopic.get(key) || []
        current.push({ session_id, offset })
        this.offsetsByPartitionTopic.set(key, current)
    }

    assignPartition(topic: string, partitions: number[]) {
        // a partition that was revoked from this consumer, could then be reassigned to it
        // on a subsequent rebalance.
        status.info('💾', 'offset_manager - checking if partitions were reassigned to this manager', {
            topic,
            partitions,
            revokedPartitions: this.revokedPartitions,
        })
        for (const p of partitions) {
            this.revokedPartitions[topic]?.delete(p)
        }
    }

    /**
     * When a rebalance occurs we need to remove all in-flight offsets for partitions that are no longer
     * assigned to this consumer.
     */
    public revokePartitions(topic: string, revokedPartitions: number[]): void {
        const assignedKeys = []
        for (const partition of revokedPartitions) {
            assignedKeys.push(`${topic}-${partition}`)
            if (!this.revokedPartitions[topic]) {
                this.revokedPartitions[topic] = new Set()
            }
            this.revokedPartitions[topic].add(partition)
        }

        const keysToDelete = new Set<string>()
        for (const [key] of this.offsetsByPartitionTopic) {
            if (assignedKeys.includes(key)) {
                keysToDelete.add(key)
            }
        }

        keysToDelete.forEach((key) => {
            this.offsetsByPartitionTopic.delete(key)
        })
    }

    // TODO: Ensure all offsets passed here are already checked to be part of the same partition
    public removeOffsets(topic: string, partition: number, offsets: number[]): number | undefined {
        // TRICKY - We want to find the newest offset from the ones being removed that is
        // older than the oldest in the list
        // e.g. [3, 4, 8, 10] -> removing [3,8] should end up with [4,10] and commit 3
        // e.g. [3, 4, 8, 10 ] -> removing [10] should end up with [3,4,8] and commit nothing

        if (!offsets.length) {
            return
        }

        let offsetToCommit: number | undefined
        const offsetsToRemove = offsets.sort((a, b) => a - b)

        const key = `${topic}-${partition}`
        const inFlightOffsets = this.offsetsByPartitionTopic.get(key)

        if (!inFlightOffsets) {
            if (this.revokedPartitions[topic]?.has(partition)) {
                // This is safe to ignore. We may have a session that is still processing after a rebalance
                // but, we don't want to commit its offsets to kafka, we no longer own it
                gaugeOffsetRemovalAfterRevoke.inc({ partition })
                return
            }
            gaugeOffsetRemovalImpossible.inc({ partition })
            status.error('💾', `offset_manager - no inflight offsets found to remove`, { partition })
            const e = new Error(`No in-flight offsets found for partition ${partition}`)
            captureException(e, { extra: { offsets, inFlightOffsets }, tags: { topic, partition } })
            throw e
        }

        inFlightOffsets.sort((a, b) => a.offset - b.offset)

        const logContext = {
            partition,
            blockingSession: !!inFlightOffsets.length ? inFlightOffsets[0].session_id : null,
            lowestInflightOffset: !!inFlightOffsets.length ? inFlightOffsets[0].offset : null,
            lowestOffsetToRemove: offsetsToRemove[0],
        }

        offsetsToRemove.forEach((offset) => {
            // Remove from the list. If it is the lowest value - set it
            const offsetIndex = inFlightOffsets.findIndex((os) => os.offset === offset)
            if (offsetIndex >= 0) {
                inFlightOffsets.splice(offsetIndex, 1)
            }

            // As the offsets are ordered we can simply check if we are removing from the start
            // Higher offsets will update this value
            if (offsetIndex === 0) {
                offsetToCommit = offset
            }
        })

        this.offsetsByPartitionTopic.set(key, inFlightOffsets)

        if (offsetToCommit !== undefined) {
            this.consumer.commitSync({
                topic,
                partition,
                // see https://kafka.apache.org/10/javadoc/org/apache/kafka/clients/consumer/KafkaConsumer.html for example
                // for some reason you commit the next offset you expect to read and not the one you actually have
                offset: offsetToCommit + 1,
            })
        }

        status.info(
            '💾',
            `offset_manager committing_offsets - ${
                offsetToCommit !== undefined ? 'committed offset' : 'no offsets to commit'
            }`,
            { ...logContext, offsetToCommit }
        )

        if (offsetToCommit !== undefined) {
            gaugeOffsetCommitted.inc()
        }

        return offsetToCommit
    }
}
