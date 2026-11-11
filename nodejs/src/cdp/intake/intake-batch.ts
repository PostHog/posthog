import { DateTime } from 'luxon'
import { Message } from 'node-rdkafka'
import { Counter } from 'prom-client'

import { logger } from '~/common/utils/logger'

import { HogFlow } from '../schema/hogflow'
import type { CyclotronV2Manager } from '../services/cyclotron-v2'
import { CyclotronV2IdempotentOutcome } from '../services/cyclotron-v2/types'
import { CdpDeadLetterService, DeadLetterCircuitBreakerError } from '../services/dead-letter/cdp-dead-letter.service'
import { EMAIL_QUEUE_PRIORITY, cdpEmailQueuedTotal } from '../services/messaging/email-priority'
import { EmailStatusService } from '../services/messaging/email-status.service'
import { HogInvocationResultsService } from '../services/monitoring/hog-invocation-results.service'
import { CyclotronJobInvocation, CyclotronJobQueueKind, HogFlowInvocationContext } from '../types'
import { IntakeMessage, RunKind, claimFingerprint, decodeIntakeMessage, intakeJobInit } from './message'

export const SEND_DEADLINE_EXCEEDED = 'send_deadline_exceeded'

const claimsCounter = new Counter({
    name: 'cdp_intake_claims_total',
    help: 'Intake runs by claim outcome: created inserted the job, replayed found the run already claimed (a redelivery, a duplicate in the batch, or a run the route claimed), mismatch found its key claimed by a different request.',
    labelNames: ['kind', 'outcome'] as const,
})

const deadLettersCounter = new Counter({
    name: 'cdp_intake_dead_letters_total',
    help: 'Intake messages that can never insert, parked on the intake dead-letter topic, by reason.',
    labelNames: ['kind', 'reason'] as const,
})

const deadlineFailuresCounter = new Counter({
    name: 'cdp_intake_deadline_failures_total',
    help: 'Intake runs that reached the consumer past their send-by deadline and failed without a job.',
    labelNames: ['kind'] as const,
})

const claimRetriesCounter = new Counter({
    name: 'cdp_intake_claim_retries_total',
    help: 'Intake claims retried after a cyclotron Postgres error.',
    labelNames: ['kind'] as const,
})

const breakerTripsCounter = new Counter({
    name: 'cdp_intake_breaker_trips_total',
    help: 'Intake batches failed instead of dead-lettered, because too much of the batch could not parse.',
    labelNames: ['kind'] as const,
})

export type IntakeBatchServices = {
    cyclotron: Pick<CyclotronV2Manager, 'createJobsIdempotently' | 'findLiveIdempotencyKeys'>
    deadLetters: Pick<CdpDeadLetterService, 'recordMessageFailure' | 'produceForBatch'>
    invocationResults: Pick<
        HogInvocationResultsService,
        'queueLifecycleRow' | 'dropQueuedRowsFor' | 'handOffQueuedRows'
    >
    emailStatus: Pick<EmailStatusService, 'queue' | 'queueFailedJob' | 'flush'>
}

export type IntakeBatchOptions = {
    kind: RunKind
    claimRetry: { initialDelayMs: number; maxElapsedMs: number }
}

type IntakeRun = { message: IntakeMessage; invocation: CyclotronJobInvocation & { hogFlow: HogFlow } }

/**
 * Inserts a batch of intake messages as cyclotron jobs, each run exactly once.
 *
 * Resolves only after every job, row and dead letter is written, so the caller stores offsets after it. Throws to
 * have Kafka redeliver the batch, and a redelivered run that already committed claims as replayed.
 */
export async function insertIntakeBatch(
    messages: Message[],
    services: IntakeBatchServices,
    options: IntakeBatchOptions
): Promise<void> {
    const runs = firstOfEachRun(parseOrDeadLetter(messages, services.deadLetters, options.kind), options.kind)
    const now = Date.now()
    const late = runs.filter((run) => isPastSendBy(run.message, now))
    const onTime = runs.filter((run) => !isPastSendBy(run.message, now))

    await failLateRuns(late, services, options.kind)
    await claimRuns(onTime, services, options)

    try {
        await services.deadLetters.produceForBatch(messages)
    } catch (error) {
        if (error instanceof DeadLetterCircuitBreakerError) {
            breakerTripsCounter.labels({ kind: options.kind }).inc()
        }
        throw error
    }
    const { produced } = await services.invocationResults.handOffQueuedRows()
    await Promise.all([produced, services.emailStatus.flush()])
}

function parseOrDeadLetter(
    messages: Message[],
    deadLetters: IntakeBatchServices['deadLetters'],
    kind: RunKind
): IntakeRun[] {
    return messages.flatMap((source) => {
        const decoded = decodeIntakeMessage(source.value)
        if (decoded.status === 'decoded') {
            return [{ message: decoded.message, invocation: intakeInvocation(decoded.message) }]
        }
        const position = { kind, topic: source.topic, partition: source.partition, offset: source.offset }
        if (!deadLetters.recordMessageFailure(source, { step: 'parse', error: decoded.reason })) {
            throw new Error(
                `Intake message at ${source.topic}[${source.partition}]@${source.offset} is ${decoded.reason} and ` +
                    'dead letters are off, so the batch fails rather than skip it'
            )
        }
        deadLettersCounter.labels({ kind, reason: decoded.reason }).inc()
        logger.warn('[CdpIntake] Dead-lettered an intake message that can never insert', {
            ...position,
            reason: decoded.reason,
        })
        return []
    })
}

function firstOfEachRun(runs: IntakeRun[], kind: RunKind): IntakeRun[] {
    const seen = new Set<string>()
    return runs.filter((run) => {
        const id = run.message.job.id.toLowerCase()
        if (seen.has(id)) {
            claimsCounter.labels({ kind, outcome: 'replayed' }).inc()
            return false
        }
        seen.add(id)
        return true
    })
}

function isPastSendBy(message: IntakeMessage, now: number): boolean {
    const sendBy = message.job.state?.state?.sendBy
    return sendBy !== undefined && Date.parse(sendBy) <= now
}

// A late run that is already claimed belongs to a job that exists, such as one the route claimed in shadow mode.
// Its rows share that job's id, so a failed row here would replace the job's own status.
async function failLateRuns(late: IntakeRun[], services: IntakeBatchServices, kind: RunKind): Promise<void> {
    if (late.length === 0) {
        return
    }
    const claimed = await services.cyclotron.findLiveIdempotencyKeys(late.map((run) => run.message.job.id))
    for (const run of late) {
        if (claimed.has(run.message.job.id.toLowerCase())) {
            claimsCounter.labels({ kind, outcome: 'replayed' }).inc()
            continue
        }
        deadlineFailuresCounter.labels({ kind }).inc()
        services.invocationResults.queueLifecycleRow(run.invocation, 'failed', {
            error: 'The run passed its send-by deadline before it was queued',
            errorKind: SEND_DEADLINE_EXCEEDED,
        })
        services.emailStatus.queueFailedJob(run.invocation, SEND_DEADLINE_EXCEEDED)
    }
}

async function claimRuns(runs: IntakeRun[], services: IntakeBatchServices, options: IntakeBatchOptions): Promise<void> {
    if (runs.length === 0) {
        return
    }
    // Queued before the claim because the running row stamps firstScheduledAt on the state, and the job must store it.
    runs.forEach((run) => services.invocationResults.queueLifecycleRow(run.invocation, 'running'))
    let outcomes: CyclotronV2IdempotentOutcome[]
    try {
        outcomes = await claimWithRetry(
            runs.map((run) => ({
                job: intakeJobInit(run.message),
                fingerprint: claimFingerprint(run.message.job.id, run.message.fingerprint),
            })),
            services.cyclotron,
            options
        )
    } catch (error) {
        services.invocationResults.dropQueuedRowsFor(runs.map((run) => run.invocation.id))
        throw error
    }

    services.invocationResults.dropQueuedRowsFor(
        runs.flatMap((run, i) => (outcomes[i] === 'created' ? [] : [run.invocation.id]))
    )
    runs.forEach((run, i) => {
        claimsCounter.labels({ kind: options.kind, outcome: outcomes[i] }).inc()
        if (outcomes[i] === 'created' && run.message.kind === 'transactional-email') {
            queueSend(run, services.emailStatus)
        } else if (outcomes[i] === 'mismatch') {
            // The run shares its id with the first request of its key, so no row can name it without naming that one.
            logger.warn('[CdpIntake] An idempotency key was reused for a different request', {
                kind: options.kind,
                team_id: run.message.teamId,
                run_id: run.message.job.id,
            })
        }
    })
}

async function claimWithRetry(
    inputs: Parameters<IntakeBatchServices['cyclotron']['createJobsIdempotently']>[0],
    cyclotron: IntakeBatchServices['cyclotron'],
    { kind, claimRetry }: IntakeBatchOptions
): Promise<CyclotronV2IdempotentOutcome[]> {
    const startedAt = Date.now()
    let delayMs = claimRetry.initialDelayMs
    for (;;) {
        try {
            return await cyclotron.createJobsIdempotently(inputs)
        } catch (error) {
            if (Date.now() - startedAt + delayMs > claimRetry.maxElapsedMs) {
                throw error
            }
            claimRetriesCounter.labels({ kind }).inc()
            logger.warn('[CdpIntake] Retrying an intake claim after a cyclotron Postgres error', {
                kind,
                runs: inputs.length,
                delay_ms: delayMs,
                error: error instanceof Error ? error.message : String(error),
            })
            await new Promise((resolve) => setTimeout(resolve, delayMs))
            delayMs *= 2
        }
    }
}

function queueSend({ message }: IntakeRun, emailStatus: IntakeBatchServices['emailStatus']): void {
    const priorityClass = message.job.priority === EMAIL_QUEUE_PRIORITY.bulk ? 'bulk' : 'fast'
    cdpEmailQueuedTotal.labels(priorityClass).inc()
    const recipient = (message.job.state?.state as Partial<HogFlowInvocationContext> | null)?.event?.properties?.to
    emailStatus.queue({
        teamId: message.teamId,
        messageId: message.job.id,
        status: 'queued',
        recipient: typeof recipient === 'string' ? recipient : undefined,
        functionId: message.job.functionId ?? undefined,
    })
}

// The consumer never loads the workflow: a deleted team or a disabled workflow still inserts, and the worker refuses
// the run. The rows need only the workflow id. The state is the message's own object, so a stamp on it reaches the job.
function intakeInvocation(message: IntakeMessage): IntakeRun['invocation'] {
    const functionId = message.job.functionId ?? ''
    return {
        id: message.job.id,
        teamId: message.teamId,
        functionId,
        parentRunId: message.job.parentRunId,
        state: message.job.state?.state ?? null,
        queue: message.job.queueName as CyclotronJobQueueKind,
        queuePriority: message.job.priority,
        queueScheduledAt: DateTime.fromISO(message.job.scheduled, { zone: 'utc' }),
        hogFlow: { id: functionId } as HogFlow,
    }
}
