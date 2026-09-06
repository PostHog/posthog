/**
 * Partition progress monitor for the evaluation scheduler.
 *
 * The consumer's own health check only proves that the poll loop still ticks. A group that
 * keeps a few partitions moving while the rest sit at a fixed offset satisfies it, and the
 * teams on the stuck partitions get no evaluations at all. This monitor samples the group's
 * committed offsets against the broker watermarks, exports the lag per partition, and reports
 * the service unhealthy when an assigned partition holds a backlog and does not advance.
 */
import { Counter, Gauge } from 'prom-client'

import { KafkaConsumerInterface } from '~/common/kafka/consumer'
import { logger } from '~/common/utils/logger'
import { HealthCheckResult, HealthCheckResultError, HealthCheckResultOk } from '~/types'

const evaluationSchedulerPartitionLag = new Gauge({
    name: 'evaluation_scheduler_partition_lag',
    help: 'Messages between the committed offset and the broker high watermark, per assigned partition',
    labelNames: ['partition'],
})

const evaluationSchedulerStalledPartitions = new Gauge({
    name: 'evaluation_scheduler_stalled_partitions',
    help: 'Number of assigned partitions that hold a backlog and have stopped committing',
})

export const evaluationSchedulerPartitionMessages = new Counter({
    name: 'evaluation_scheduler_partition_messages_total',
    help: 'Kafka messages received by the evaluation scheduler, per partition',
    labelNames: ['partition'],
})

const evaluationSchedulerLagSampleFailures = new Counter({
    name: 'evaluation_scheduler_lag_sample_failures_total',
    help: 'Number of failed attempts to sample committed offsets or broker watermarks',
})

/** The part of the consumer this monitor needs. Both consumer implementations satisfy it. */
export type PartitionProgressSource = Pick<KafkaConsumerInterface, 'committedOffsets' | 'queryWatermarkOffsets'>

export interface PartitionProgressMonitorConfig {
    topic: string
    groupId: string
    /** How often to sample the group's offsets. */
    pollIntervalMs: number
    /** How long a backlogged partition can stay at one offset before the service reports unhealthy. Zero disables the health gate. */
    stallThresholdMs: number
    /** Lag a partition must hold before a lack of progress counts as a stall. */
    stallMinLag: number
}

interface PartitionState {
    committedOffset: number
    lastAdvancedAt: number
}

interface StalledPartition {
    partition: number
    lag: number
    stalledForMs: number
}

export class PartitionProgressMonitor {
    private states = new Map<number, PartitionState>()
    private stalled: StalledPartition[] = []
    private timer: NodeJS.Timeout | null = null

    constructor(
        private consumer: PartitionProgressSource,
        private config: PartitionProgressMonitorConfig
    ) {}

    public start(): void {
        this.timer = setInterval(() => {
            void this.sample()
        }, this.config.pollIntervalMs)
        this.timer.unref()
    }

    public stop(): void {
        if (this.timer) {
            clearInterval(this.timer)
            this.timer = null
        }
    }

    public async sample(now: number = Date.now()): Promise<void> {
        try {
            const committed = await this.consumer.committedOffsets()
            // A partition with no commit yet reports a negative sentinel offset, which says
            // nothing about progress, so it stays out of the sample.
            const assigned = committed.filter((entry) => entry.topic === this.config.topic && entry.offset >= 0)

            const lags = await Promise.all(
                assigned.map(async (entry) => {
                    const [, high] = await this.consumer.queryWatermarkOffsets(this.config.topic, entry.partition)
                    return {
                        partition: entry.partition,
                        committedOffset: entry.offset,
                        lag: Math.max(high - entry.offset, 0),
                    }
                })
            )

            this.pruneRevokedPartitions(new Set(lags.map(({ partition }) => partition)))

            const stalled: StalledPartition[] = []
            for (const { partition, committedOffset, lag } of lags) {
                const previous = this.states.get(partition)
                const advanced = !previous || committedOffset > previous.committedOffset
                const lastAdvancedAt = advanced ? now : previous.lastAdvancedAt
                this.states.set(partition, { committedOffset, lastAdvancedAt })

                evaluationSchedulerPartitionLag.labels({ partition: String(partition) }).set(lag)

                const stalledForMs = now - lastAdvancedAt
                if (this.isStalled(lag, stalledForMs)) {
                    stalled.push({ partition, lag, stalledForMs })
                }
            }

            this.stalled = stalled
            evaluationSchedulerStalledPartitions.set(stalled.length)

            if (stalled.length > 0) {
                logger.warn('Evaluation scheduler partitions are not progressing', {
                    groupId: this.config.groupId,
                    topic: this.config.topic,
                    assignedPartitions: lags.length,
                    stalled,
                })
            }
        } catch (error) {
            // Keep the last sample rather than reporting a stall: a broker hiccup must not
            // restart a consumer that is working.
            evaluationSchedulerLagSampleFailures.inc()
            logger.error('Failed to sample evaluation scheduler partition progress', {
                groupId: this.config.groupId,
                topic: this.config.topic,
                error: error instanceof Error ? error.message : String(error),
            })
        }
    }

    public health(): HealthCheckResult {
        if (this.stalled.length === 0) {
            return new HealthCheckResultOk()
        }

        const partitions = this.stalled.map(({ partition }) => partition)
        return new HealthCheckResultError(
            `Evaluation scheduler made no progress on partitions ${partitions.join(', ')}`,
            {
                topic: this.config.topic,
                groupId: this.config.groupId,
                stalled: this.stalled,
                stallThresholdMs: this.config.stallThresholdMs,
                stallMinLag: this.config.stallMinLag,
            }
        )
    }

    private isStalled(lag: number, stalledForMs: number): boolean {
        if (this.config.stallThresholdMs <= 0) {
            return false
        }
        return lag >= this.config.stallMinLag && stalledForMs >= this.config.stallThresholdMs
    }

    private pruneRevokedPartitions(assigned: Set<number>): void {
        for (const partition of this.states.keys()) {
            if (!assigned.has(partition)) {
                this.states.delete(partition)
                evaluationSchedulerPartitionLag.remove({ partition: String(partition) })
            }
        }
    }
}
