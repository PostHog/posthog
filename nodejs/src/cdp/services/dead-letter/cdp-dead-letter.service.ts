import { Message } from 'node-rdkafka'
import { Counter } from 'prom-client'

import { logger } from '~/common/utils/logger'

// Type-only: the service sits below cdp-services in the import graph and must not pull it in at runtime.
import type { CdpOutputs } from '../../cdp-services'
import type { CdpEventsDlqOutput, CdpInternalEventsDlqOutput } from '../../outputs/outputs'
import type { DeadLetterFailure, DeadLetterStep, HogFunctionInvocationGlobals } from '../../types'

export type CdpDlqOutput = CdpEventsDlqOutput | CdpInternalEventsDlqOutput

const counterDeadLetterMessages = new Counter({
    name: 'cdp_dead_letter_messages_total',
    help: 'An event was parked on a CDP dead-letter topic',
    labelNames: ['output', 'step'],
})

const counterDeadLetterProduceFailures = new Counter({
    name: 'cdp_dead_letter_produce_failures_total',
    help: 'A CDP dead-letter record could not be produced, so its batch failed',
    labelNames: ['output'],
})

const counterProcessFailures = new Counter({
    name: 'cdp_dead_letter_process_failures_total',
    help: 'An event threw outside the failures the pipeline handles per function',
    labelNames: ['output'],
})

const counterDeadLetterBatchFailures = new Counter({
    name: 'cdp_dead_letter_batch_failures_total',
    help: 'A batch failed instead of being dead-lettered, because too much of it was failing',
    labelNames: ['output'],
})

/** An error message can quote a template value, so it is truncated and never indexed. */
const MAX_REASON_BYTES = 1024

/**
 * Fewest unexpected failures that can trip the circuit breaker, whatever the ratio says.
 *
 * A ratio alone says nothing on a small batch: one poison event in a batch of one is 100% of it,
 * and breaking there would stall the partition on exactly the event this path exists to park. The
 * breaker is for a deployment that is broken everywhere, and that always shows up as more than a
 * couple of events.
 */
const MIN_UNEXPECTED_TO_BREAK = 3

export interface CdpDeadLetterServiceConfig {
    CDP_DLQ_ENABLED: boolean
    CDP_DLQ_BATCH_FAIL_RATIO: number
}

/** Raised instead of parking, when a whole batch looks broken rather than a few events in it. */
export class DeadLetterCircuitBreakerError extends Error {
    constructor(parked: number, batchSize: number) {
        super(
            `Refusing to dead-letter ${parked} of ${batchSize} messages: an unexpected failure this ` +
                'wide is a bug in this deployment, not poison in the stream'
        )
        this.name = 'DeadLetterCircuitBreakerError'
    }
}

export interface CdpDeadLetterServiceOptions {
    outputs: CdpOutputs
    output: CdpDlqOutput
    consumerGroup: string
    /**
     * The Kafka message a set of globals was built from.
     *
     * The consumer is the only layer holding both, so it supplies the lookup. Matching on a key
     * instead would mean naming the event, and the only candidate is the client-supplied UUID,
     * which is unique only within a team on a topic that carries every team.
     */
    resolveMessage: (globals: HogFunctionInvocationGlobals) => Message | undefined
}

/**
 * Parks events that matched a function but produced no invocation.
 *
 * The record is the original message bytes. Headers name the functions that failed, so a replay
 * rebuilds only those and the functions that delivered the first time do not deliver twice.
 *
 * Known gap: a function with mappings is named as a whole. `buildHogFunctionInvocations` builds one
 * invocation per mapping, so a function whose mapping A delivered and mapping B failed comes back
 * as one id, and a replay re-runs both. Mappings carry no stable identifier, only a position that
 * moves when the config is edited, so there is nothing to name. Accepted: the alternative is a
 * schema change, and re-delivering one mapping is a smaller problem than losing the other.
 *
 * Failures are collected during a batch and produced before the consumer stores its offsets, so a
 * record always exists before the source message is considered handled.
 */
export class CdpDeadLetterService {
    private failures: DeadLetterFailure[] = []
    /** Failures that already carry their message, because nothing parsed an event UUID out of it. */
    private messageFailures: { message: Message; failure: DeadLetterFailure }[] = []

    constructor(
        private config: CdpDeadLetterServiceConfig,
        private options: CdpDeadLetterServiceOptions
    ) {}

    /**
     * Fails startup when the topic is missing, rather than at the first failure.
     *
     * Without this a misrouted or absent topic stays invisible while clean batches commit, and the
     * first event that needed parking is the one that stops the consumer.
     */
    public async checkTopic(): Promise<void> {
        if (!this.config.CDP_DLQ_ENABLED) {
            return
        }
        const failures = await this.options.outputs.checkTopics()
        if (failures.includes(this.options.output)) {
            throw new Error(
                `CDP_DLQ_ENABLED is on but the dead-letter topic for ${this.options.output} is not reachable — ` +
                    'refusing to start, because events would be dropped the moment one needed parking'
            )
        }
    }

    public recordBuildFailures(failures: DeadLetterFailure[]): void {
        if (!this.config.CDP_DLQ_ENABLED || !failures.length) {
            return
        }
        this.failures.push(...failures)
    }

    /**
     * Records an event that threw somewhere the per-function handling did not cover.
     *
     * The event is known, so this resolves back to its message by UUID like a build failure. The
     * record names no function, which tells a replay to rebuild every function of the team: nothing
     * was built the first time, so nothing can be delivered twice.
     */
    public recordProcessFailure(globals: HogFunctionInvocationGlobals, error: unknown): void {
        if (!this.config.CDP_DLQ_ENABLED) {
            return
        }
        this.failures.push({
            globals,
            step: 'process',
            error: error instanceof Error ? error.message : String(error),
        })
        counterProcessFailures.labels({ output: this.options.output }).inc()
    }

    /**
     * Records a failure against a message directly, for the steps that have no event to key on.
     *
     * A message that could not be parsed has no UUID to resolve later, and an event that threw
     * somewhere unexpected should not depend on the parse having produced one either.
     */
    public recordMessageFailure(message: Message, failure: Omit<DeadLetterFailure, 'globals'>): void {
        if (!this.config.CDP_DLQ_ENABLED) {
            return
        }
        this.messageFailures.push({ message, failure: failure as DeadLetterFailure })
    }

    /**
     * Produces one record per event and step, then clears the buffer.
     *
     * A produce failure rethrows: losing the record and advancing past the source message would
     * lose the event for good, which is the outcome this whole path exists to prevent.
     */
    public async produceForBatch(messages: Message[]): Promise<void> {
        const failures = this.failures
        const messageFailures = this.messageFailures
        this.failures = []
        this.messageFailures = []

        if (!failures.length && !messageFailures.length) {
            return
        }

        // Two conditions, both required: at least MIN_UNEXPECTED_TO_BREAK failures, and more than
        // CDP_DLQ_BATCH_FAIL_RATIO of the batch. In a batch of 500 at the default 0.1 that is 51
        // events; in a batch of 4 it is 3; in a batch of 2 nothing can trip it.
        //
        // Tripping throws before a single record is written, so no offsets are stored and the
        // partition stalls. That is the point. An unexpected failure across a slice of a batch is a
        // bug in this deployment, not poison in the stream, and parking it all would drain the
        // stream into a side topic while every dashboard stayed green: lag zero, consumer healthy,
        // throughput normal. Stalling is worse for latency and far better for being noticed,
        // because the lag alert that already exists fires on it.
        //
        // `filter` and `inputs` are deliberately excluded. One broken builtin legitimately breaks
        // every function in a batch, which is the incident this whole path was built for, so
        // counting those would make the breaker fire hardest exactly when it must not.
        const unexpected = failures.filter((failure) => failure.step === 'process').length
        if (
            unexpected >= MIN_UNEXPECTED_TO_BREAK &&
            messages.length &&
            unexpected > messages.length * this.config.CDP_DLQ_BATCH_FAIL_RATIO
        ) {
            counterDeadLetterBatchFailures.labels({ output: this.options.output }).inc()
            throw new DeadLetterCircuitBreakerError(unexpected, messages.length)
        }

        // Grouped on the globals object itself, so one record covers one event and one step. Object
        // identity needs no key, which is why there is nothing here to collide: the alternative was
        // naming the event by its client-supplied UUID, unique only within a team.
        const records = new Map<HogFunctionInvocationGlobals, Map<DeadLetterStep, DeadLetterFailure[]>>()
        for (const failure of failures) {
            const byStep = records.get(failure.globals) ?? new Map<DeadLetterStep, DeadLetterFailure[]>()
            byStep.set(failure.step, [...(byStep.get(failure.step) ?? []), failure])
            records.set(failure.globals, byStep)
        }

        try {
            await Promise.all([
                ...messageFailures.map(({ message, failure }) => this.produceRecord(message, [failure])),
                ...[...records.entries()].flatMap(([globals, byStep]) => {
                    const message = this.options.resolveMessage(globals)
                    if (!message) {
                        // Only reachable if the consumer stopped tracking a message it built globals
                        // from, which would be a bug in the consumer rather than in the data.
                        logger.warn('🔴', '[CdpDeadLetterService] No source message for build failure', {
                            teamId: globals.project.id,
                            step: [...byStep.keys()].join(','),
                        })
                        return []
                    }
                    return [...byStep.values()].map((group) => this.produceRecord(message, group))
                }),
            ])
        } catch (error) {
            counterDeadLetterProduceFailures.labels({ output: this.options.output }).inc()
            logger.error('🔴', '[CdpDeadLetterService] Failed to produce dead-letter records', { error })
            throw error
        }
    }

    private async produceRecord(message: Message, group: DeadLetterFailure[]): Promise<void> {
        const step: DeadLetterStep = group[0].step
        // An empty id list is meaningful: nothing was built for this event, so a replay rebuilds
        // every function of the team rather than a named subset.
        const hogFunctionIds = group.flatMap((f) => (f.sourceKind === 'hog_function' && f.sourceId ? [f.sourceId] : []))
        const hogFlowIds = group.flatMap((f) => (f.sourceKind === 'hog_flow' && f.sourceId ? [f.sourceId] : []))

        await this.options.outputs.produce(this.options.output, {
            value: message.value,
            key: message.key ?? null,
            headers: {
                ...copyHeaders(message),

                // Mechanism. The replay reads these to decide what to rebuild. An empty id list is
                // meaningful: nothing was built for this event, so rebuild every function of the
                // team. The team itself is not a header, because the event body already carries it
                // and that is what the replay rebuilds from.
                dlq_hog_function_ids: hogFunctionIds.join(','),
                dlq_hog_flow_ids: hogFlowIds.join(','),

                // Scoping. Not needed to replay a record, but an operator narrows a run with these,
                // and they are read from headers alone so a scan over millions of records does not
                // deserialize the bodies it is going to skip.
                dlq_step: step,
                dlq_reason: truncate(group[0].error, MAX_REASON_BYTES),
                dlq_timestamp: new Date().toISOString(),
                dlq_team_id: group[0].globals ? String(group[0].globals.project.id) : '',

                // Diagnostics. Nothing reads these. They are here so a person looking at the topic
                // can find the source message this record came from.
                dlq_topic: message.topic,
                dlq_partition: String(message.partition),
                dlq_offset: String(message.offset),
                dlq_consumer_group: this.options.consumerGroup,
            },
        })

        counterDeadLetterMessages.labels({ output: this.options.output, step }).inc()
    }
}

function copyHeaders(message: Message): Record<string, string> {
    const copied: Record<string, string> = {}
    for (const header of message.headers ?? []) {
        for (const [key, value] of Object.entries(header)) {
            if (value === undefined) {
                continue
            }
            copied[key] = Buffer.isBuffer(value) ? value.toString() : String(value)
        }
    }
    return copied
}

function truncate(value: string, maxBytes: number): string {
    const buffer = Buffer.from(value, 'utf8')
    return buffer.byteLength <= maxBytes ? value : buffer.subarray(0, maxBytes).toString('utf8')
}
