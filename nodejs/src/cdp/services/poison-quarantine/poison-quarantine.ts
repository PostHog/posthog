import { Message } from 'node-rdkafka'
import { Counter, Histogram } from 'prom-client'

import { logger } from '~/common/utils/logger'

import type { CdpOutputs } from '../../cdp-services'
import { CDP_QUARANTINE_OUTPUT } from '../../outputs/outputs'
import { MAX_REASON_BYTES, copyHeaders, truncateUtf8 } from '../dead-letter/cdp-dead-letter.service'

export type EachBatchResult = { backgroundTask?: Promise<unknown> } | void
export type EachBatchHandler = (messages: Message[]) => Promise<EachBatchResult>

export interface PoisonQuarantineConfig {
    CDP_POISON_QUARANTINE_ENABLED: boolean
}

export interface QuarantineSource {
    consumerGroup: string
    mayHaveSideEffects: boolean
}

export const MAX_QUARANTINED_PER_BATCH = 3
const ATTEMPTS_ALONE = 2
const RECORDS_RUN_AT_ONCE = 10

const counterQuarantinedRecords = new Counter({
    name: 'cdp_poison_quarantined_records_total',
    help: 'A record failed alone twice and was written to the quarantine topic, so its partition moved on',
    labelNames: ['consumer_group'],
})

const histogramIsolationDuration = new Histogram({
    name: 'cdp_poison_isolation_duration_seconds',
    help: 'How long a partition waited while a failed batch was retried one record at a time',
    labelNames: ['consumer_group', 'outcome'],
    buckets: [0.1, 0.5, 1, 5, 15, 30, 60, 120, 300],
})

type RanAlone = { message: Message; backgroundTask?: Promise<unknown> }
type FailedAlone = { message: Message; error: unknown }
type AloneOutcome = RanAlone | FailedAlone

const hasFailedAlone = (outcome: AloneOutcome): outcome is FailedAlone => 'error' in outcome
const hasRunAlone = (outcome: AloneOutcome): outcome is RanAlone => !hasFailedAlone(outcome)

export class PoisonQuarantine {
    constructor(
        private config: PoisonQuarantineConfig,
        private outputs: CdpOutputs
    ) {}

    public get enabled(): boolean {
        return this.config.CDP_POISON_QUARANTINE_ENABLED
    }

    public wrap(handler: EachBatchHandler, source: QuarantineSource): EachBatchHandler {
        if (!this.enabled) {
            return handler
        }
        return async (messages) => {
            try {
                return await handler(messages)
            } catch (batchError) {
                return await this.isolate(handler, messages, batchError, source)
            }
        }
    }

    private async isolate(
        handler: EachBatchHandler,
        messages: Message[],
        batchError: unknown,
        source: QuarantineSource
    ): Promise<EachBatchResult> {
        const stopTimer = histogramIsolationDuration.startTimer({ consumer_group: source.consumerGroup })
        logger.warn('☣️', 'cdp_poison_batch_failed_retrying_alone', {
            consumerGroup: source.consumerGroup,
            size: messages.length,
            error: String(batchError),
        })

        const outcomes = await runInGroups(messages, RECORDS_RUN_AT_ONCE, (message) => runAlone(handler, message))
        const poisoned = outcomes.filter(hasFailedAlone)

        if (poisoned.length > MAX_QUARANTINED_PER_BATCH) {
            stopTimer({ outcome: 'rethrown' })
            logger.error('☣️', 'cdp_poison_too_many_failed_alone', {
                consumerGroup: source.consumerGroup,
                failedAlone: poisoned.length,
            })
            throw batchError
        }

        await Promise.all(poisoned.map(({ message, error }) => this.quarantine(message, error, source)))
        stopTimer({ outcome: poisoned.length ? 'quarantined' : 'recovered' })

        return {
            backgroundTask: Promise.all(
                outcomes.filter(hasRunAlone).flatMap((outcome) => outcome.backgroundTask ?? [])
            ),
        }
    }

    public async quarantine(message: Message, error: unknown, source: QuarantineSource): Promise<void> {
        await this.outputs.produce(CDP_QUARANTINE_OUTPUT, {
            value: message.value,
            key: message.key ?? null,
            headers: {
                ...copyHeaders(message),
                quarantine_reason: truncateUtf8(
                    error instanceof Error ? error.message : String(error),
                    MAX_REASON_BYTES
                ),
                quarantine_may_have_side_effects: String(source.mayHaveSideEffects),
                quarantine_timestamp: new Date().toISOString(),
                quarantine_topic: message.topic,
                quarantine_partition: String(message.partition),
                quarantine_offset: String(message.offset),
                quarantine_consumer_group: source.consumerGroup,
            },
        })
        counterQuarantinedRecords.labels({ consumer_group: source.consumerGroup }).inc()
        logger.error('☣️', 'cdp_poison_record_quarantined', {
            consumerGroup: source.consumerGroup,
            topic: message.topic,
            partition: message.partition,
            offset: message.offset,
            error: String(error),
        })
    }
}

async function runAlone(handler: EachBatchHandler, message: Message): Promise<AloneOutcome> {
    let lastError: unknown
    for (let attempt = 0; attempt < ATTEMPTS_ALONE; attempt++) {
        try {
            const result = await handler([message])
            return { message, backgroundTask: result?.backgroundTask }
        } catch (error) {
            lastError = error
        }
    }
    return { message, error: lastError }
}

async function runInGroups<T, R>(items: T[], groupSize: number, run: (item: T) => Promise<R>): Promise<R[]> {
    const results: R[] = []
    for (let start = 0; start < items.length; start += groupSize) {
        results.push(...(await Promise.all(items.slice(start, start + groupSize).map(run))))
    }
    return results
}
