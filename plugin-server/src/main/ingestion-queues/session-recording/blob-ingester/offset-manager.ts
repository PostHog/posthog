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
 */

import { KafkaConsumer } from 'node-rdkafka-acosom'
import { Gauge } from 'prom-client'

import { status } from '../../../../utils/status'

export const gaugeOffsetCommitAttempted = new Gauge({
    name: 'offset_manager_offset_commit_attempted',
    help: 'When a session manager flushes to S3 it reports which offset on the partition it flushed. This may result in that offset being committed',
    labelNames: ['committed'],
})

export const gaugeOffsetRemovalImpossible = new Gauge({
    name: 'offset_manager_offset_removal_impossible',
    help: 'When a session manager flushes to S3 it reports which offset on the partition it flushed. That should always match an offset being managed',
})

interface OffsetSummary {
    lowest: number | null
    highest: number | null
    count: number | null
}

const offsetSummary = (offsets: number[] | undefined): OffsetSummary => {
    // assumes the offsets have been sorted already
    return {
        lowest: !!offsets?.length ? offsets[0] : null,
        highest: !!offsets?.length ? offsets[offsets.length - 1] : null,
        count: offsets?.length || null,
    }
}

export class OffsetManager {
    // We have to track every message's offset so that we can commit them only after they've been written to S3
    offsetsByPartitionTopic: Map<string, number[]> = new Map()

    constructor(private consumer: KafkaConsumer) {}

    public addOffset(topic: string, partition: number, offset: number): void {
        const key = `${topic}-${partition}`

        if (!this.offsetsByPartitionTopic.has(key)) {
            this.offsetsByPartitionTopic.set(key, [])
        }

        const current = this.offsetsByPartitionTopic.get(key) || []
        current.push(offset)
        current.sort((a, b) => a - b)
        this.offsetsByPartitionTopic.set(key, current)
    }

    /**
     * When a rebalance occurs we need to remove all in-flight offsets for partitions that are no longer
     * assigned to this consumer.
     */
    public revokePartitions(topic: string, revokedPartitions: number[]): void {
        const assignedKeys = revokedPartitions.map((partition) => `${topic}-${partition}`)

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
            gaugeOffsetRemovalImpossible.inc()
            status.warn('💾', `offset_manager - no inflight offsets found to remove`, { partition })
            return
        }

        offsetsToRemove.forEach((offset) => {
            // Remove from the list. If it is the lowest value - set it
            const offsetIndex = inFlightOffsets.indexOf(offset)
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

        const inflightOffsetSummary = offsetSummary(inFlightOffsets)
        const offsetsToRemoveSummary = offsetSummary(offsetsToRemove)
        const logContext = {
            offsetToCommit,
            inflightOffsetsCount: inflightOffsetSummary.count,
            lowestInflightOffset: inflightOffsetSummary.highest,
            highestInflightOffset: inflightOffsetSummary.lowest,
            offsetsToRemoveCount: offsetsToRemoveSummary.count,
            lowestOffsetToRemove: offsetsToRemoveSummary.highest,
            highestOffsetToRemove: offsetsToRemoveSummary.lowest,
            partition,
        }

        if (offsetToCommit !== undefined) {
            this.consumer.commit({
                topic,
                partition,
                offset: offsetToCommit,
            })
        }

        status.info(
            '💾',
            `offset_manager committing_offsets - ${
                offsetToCommit !== undefined ? 'committed offset' : 'no offsets to commit'
            }`,
            logContext
        )
        gaugeOffsetCommitAttempted.labels({ committed: offsetToCommit !== undefined ? 'true' : 'false' }).inc()

        return offsetToCommit
    }
}
