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

import { Consumer } from 'kafkajs'

import { status } from '../../../../utils/status'

export class OffsetManager {
    // We have to track every message's offset so that we can commit them only after they've been written to S3
    // TODO: Change this to an ordered array.
    offsetsByPartitionTopic: Map<string, number[]> = new Map()

    constructor(private consumer: Consumer) {}

    public addOffset(topic: string, partition: number, offset: number): void {
        const key = `${topic}-${partition}`

        if (!this.offsetsByPartitionTopic.has(key)) {
            this.offsetsByPartitionTopic.set(key, [])
        }

        // TODO: We should parseInt when we handle the message
        this.offsetsByPartitionTopic.get(key)?.push(offset)
    }

    // TODO: Ensure all offsets passed here are already checked to be part of the same partition
    public async removeOffsets(topic: string, partition: number, offsets: number[]): Promise<number | undefined> {
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

        status.info('💾', `Current offsets: ${inFlightOffsets}`)
        status.info('💾', `Removing offsets: ${offsets}`)

        if (!inFlightOffsets) {
            status.error('💾', `No offsets found for key: ${key}. This should never happen`)
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

        if (offsetToCommit) {
            status.info('💾', `Committing offset ${offsetToCommit} for ${topic}-${partition}`)
            await this.consumer.commitOffsets([
                {
                    topic,
                    partition,
                    offset: offsetToCommit.toString(),
                },
            ])
        } else {
            status.info('💾', `No offset to commit from: ${inFlightOffsets}`)
        }

        return offsetToCommit
    }
}
