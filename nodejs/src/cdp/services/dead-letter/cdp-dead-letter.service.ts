import { Message } from 'node-rdkafka'
import { Counter } from 'prom-client'

import { logger } from '~/common/utils/logger'

import type { CdpOutputs } from '../../cdp-services'
import type { CdpEventsDlqOutput } from '../../outputs/outputs'
import type { DeadLetterStep, HogFunctionInvocationGlobals, InvocationBuildFailure } from '../../types'

/** In memory only. What leaves is the original event bytes plus string headers. */
type PendingFailure = {
    /** Absent when nothing was built for the event, so no single function is at fault. */
    sourceId?: string
    sourceKind?: 'hog_function' | 'hog_flow'
    step: DeadLetterStep
    error: string
}

export type CdpDlqOutput = CdpEventsDlqOutput

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

/** A ratio says nothing on a small batch: one bad event in a batch of one is 100% of it. */
const MIN_UNEXPECTED_TO_BREAK = 3

export interface CdpDeadLetterServiceConfig {
    CDP_DLQ_ENABLED: boolean
    CDP_DLQ_BATCH_FAIL_RATIO: number
}

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
    resolveMessage: (globals: HogFunctionInvocationGlobals) => Message | undefined
}

/**
 * Parks events that matched a function but produced no invocation.
 *
 * Headers name the functions that failed, so a replay rebuilds only those.
 *
 * Known gap: a function with mappings is named as a whole, so a replay re-runs a mapping that
 * already delivered. Mappings carry no stable id, only a position that moves when the config is
 * edited. Accepted over a schema change.
 */
/**
 * What the invocation pipelines need from a dead-letter service.
 *
 * Narrow on purpose, so a consumer with no topic to park on can still be told what failed. The
 * replay worker passes a collector rather than nothing, because a rebuild that fails the same way
 * a second time has to block the run instead of committing past the record.
 */
export interface InvocationFailureSink {
    recordBuildFailures(globals: HogFunctionInvocationGlobals, failures: InvocationBuildFailure[]): void
    /** False means the event was not retained, so the caller must let the error through. */
    recordProcessFailure(
        globals: HogFunctionInvocationGlobals,
        error: unknown,
        sourceKind: 'hog_function' | 'hog_flow'
    ): boolean
}

export class CdpDeadLetterService implements InvocationFailureSink {
    /** Kept grouped by event, which is the shape the records are written in. */
    private failures: { globals: HogFunctionInvocationGlobals; failures: PendingFailure[] }[] = []
    private messageFailures: { message: Message; failure: PendingFailure }[] = []

    constructor(
        private config: CdpDeadLetterServiceConfig,
        private options: CdpDeadLetterServiceOptions
    ) {}

    /** Without this a misrouted topic hides until the first event that needed parking. */
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

    public recordBuildFailures(globals: HogFunctionInvocationGlobals, failures: InvocationBuildFailure[]): void {
        if (!this.config.CDP_DLQ_ENABLED || !failures.length) {
            return
        }
        this.failures.push({ globals, failures })
    }

    /**
     * Names no single source, because the throw was not attributable to one, but does name the kind.
     *
     * The two pipelines run against the same event, so one can queue its invocations while the
     * other throws. Without the kind a replay would rebuild both, re-delivering whatever the
     * healthy pipeline already sent.
     *
     * False means the event was not retained, so the caller must let the error through.
     */
    public recordProcessFailure(
        globals: HogFunctionInvocationGlobals,
        error: unknown,
        sourceKind: 'hog_function' | 'hog_flow'
    ): boolean {
        if (!this.config.CDP_DLQ_ENABLED) {
            return false
        }
        this.failures.push({
            globals,
            failures: [{ step: 'process', sourceKind, error: error instanceof Error ? error.message : String(error) }],
        })
        counterProcessFailures.labels({ output: this.options.output }).inc()
        return true
    }

    /** For a message that never became an event, so there are no globals to attach it to. */
    public recordMessageFailure(message: Message, failure: Omit<PendingFailure, 'sourceId' | 'sourceKind'>): void {
        if (!this.config.CDP_DLQ_ENABLED) {
            return
        }
        this.messageFailures.push({ message, failure })
    }

    /**
     * Produces one record per event and step, then clears the buffer.
     *
     * A produce failure rethrows: advancing past the source message with no record loses the event.
     */
    public async produceForBatch(messages: Message[]): Promise<void> {
        const failures = this.failures
        const messageFailures = this.messageFailures
        this.failures = []
        this.messageFailures = []

        if (!failures.length && !messageFailures.length) {
            return
        }

        // Stalling the partition beats parking a whole batch: draining the stream into a side topic
        // leaves lag, health and throughput all reading normal, so nobody notices. `filter` and
        // `inputs` never count, because one broken builtin legitimately breaks a whole batch and
        // those records are the point.
        const unexpected = new Set(
            failures
                .filter((entry) => entry.failures.some((failure) => failure.step === 'process'))
                .map((entry) => entry.globals)
        ).size
        if (
            unexpected >= MIN_UNEXPECTED_TO_BREAK &&
            messages.length &&
            unexpected > messages.length * this.config.CDP_DLQ_BATCH_FAIL_RATIO
        ) {
            counterDeadLetterBatchFailures.labels({ output: this.options.output }).inc()
            throw new DeadLetterCircuitBreakerError(unexpected, messages.length)
        }

        // Grouped on the globals object itself, so one record covers one event and one step. Both
        // pipelines record against the same event, so an event can arrive here more than once.
        const records = new Map<HogFunctionInvocationGlobals, Map<DeadLetterStep, PendingFailure[]>>()
        for (const entry of failures) {
            const byStep = records.get(entry.globals) ?? new Map<DeadLetterStep, PendingFailure[]>()
            for (const failure of entry.failures) {
                const forStep = byStep.get(failure.step)
                if (forStep) {
                    forStep.push(failure)
                } else {
                    byStep.set(failure.step, [failure])
                }
            }
            records.set(entry.globals, byStep)
        }

        try {
            await Promise.all([
                ...messageFailures.map(({ message, failure }) => this.produceRecord(message, null, [failure])),
                ...[...records.entries()].flatMap(([globals, byStep]) => {
                    const message = this.options.resolveMessage(globals)
                    if (!message) {
                        // A consumer that stopped tracking a message it built globals from. There
                        // are no bytes to park, so failing the batch is the only way to keep the
                        // event. This throws inside the try below, so it is counted and logged.
                        throw new Error(
                            `No source message for a build failure on team ${globals.project.id}: the event ` +
                                'cannot be parked, so the batch fails rather than advancing past it'
                        )
                    }
                    return [...byStep.values()].map((group) => this.produceRecord(message, globals.project.id, group))
                }),
            ])
        } catch (error) {
            counterDeadLetterProduceFailures.labels({ output: this.options.output }).inc()
            logger.error('🔴', '[CdpDeadLetterService] Failed to produce dead-letter records', { error })
            throw error
        }
    }

    private async produceRecord(message: Message, teamId: number | null, group: PendingFailure[]): Promise<void> {
        const step: DeadLetterStep = group[0].step
        const hogFunctionIds = group.flatMap((f) => (f.sourceKind === 'hog_function' && f.sourceId ? [f.sourceId] : []))
        const hogFlowIds = group.flatMap((f) => (f.sourceKind === 'hog_flow' && f.sourceId ? [f.sourceId] : []))
        const kinds = [...new Set(group.flatMap((f) => (f.sourceKind ? [f.sourceKind] : [])))]

        await this.options.outputs.produce(this.options.output, {
            value: message.value,
            key: message.key ?? null,
            headers: {
                ...copyHeaders(message),

                // Mechanism. What the replay worker reads. `dlq_step` marks the record as one of
                // ours, and the id lists say what to rebuild — empty means rebuild every source
                // for the team, because nothing was built the first time.
                dlq_step: step,
                dlq_hog_function_ids: hogFunctionIds.join(','),
                dlq_hog_flow_ids: hogFlowIds.join(','),
                // Which kinds a replay may rebuild. Carries the whole answer when no id is named:
                // empty means nothing was built at all, so both kinds are in scope.
                dlq_kinds: kinds.join(','),

                // Diagnostics. Nothing branches on these. They are what a person has to work with
                // when they open the topic and need to know what failed, for whom, and where it
                // came from, without deserializing the bodies.
                dlq_reason: truncate(group[0].error, MAX_REASON_BYTES),
                dlq_timestamp: new Date().toISOString(),
                dlq_team_id: teamId === null ? '' : String(teamId),
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
