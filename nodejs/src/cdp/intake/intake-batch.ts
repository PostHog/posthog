import { DateTime } from 'luxon'
import { Message } from 'node-rdkafka'
import { Counter } from 'prom-client'

import { logger } from '~/common/utils/logger'
import { retryIfRetriable } from '~/common/utils/retries'

import { HogFlow } from '../schema/hogflow'
import type { CyclotronV2Manager } from '../services/cyclotron-v2'
import { IDEMPOTENCY_KEY_TTL_MS } from '../services/cyclotron-v2/manager'
import { CyclotronV2IdempotentOutcome } from '../services/cyclotron-v2/types'
import { CdpDeadLetterService, DeadLetterCircuitBreakerError } from '../services/dead-letter/cdp-dead-letter.service'
import { EMAIL_QUEUE_PRIORITY, cdpEmailQueuedTotal } from '../services/messaging/email-priority'
import { EmailStatusService, messageCreatedAtOf } from '../services/messaging/email-status.service'
import { HogInvocationResultsService } from '../services/monitoring/hog-invocation-results.service'
import { CyclotronJobInvocation, CyclotronJobQueueKind, HogFlowInvocationContext } from '../types'
import {
    IntakeDeadLetterReason,
    IntakeMessage,
    RunKind,
    claimFingerprint,
    decodeIntakeMessage,
    intakeJobInit,
} from './message'

const claimsCounter = new Counter({
    name: 'cdp_intake_claims_total',
    help: 'Intake runs by claim outcome: created inserted the job, replayed found the run already claimed (a redelivery, a duplicate in the batch, or a run the route claimed), mismatch found its key claimed by a different request, shadow_expired skipped a shadow copy too old to trust its claim.',
    labelNames: ['kind', 'outcome'] as const,
})

const deadLettersCounter = new Counter({
    name: 'cdp_intake_dead_letters_total',
    help: 'Intake messages that can never insert, parked on the intake dead-letter topic, by reason.',
    labelNames: ['kind', 'reason'] as const,
})

const claimErrorsCounter = new Counter({
    name: 'cdp_intake_claim_errors_total',
    help: 'Intake claims that hit a cyclotron Postgres error. The claim retries until its time runs out, then the batch fails.',
    labelNames: ['kind'] as const,
})

const breakerTripsCounter = new Counter({
    name: 'cdp_intake_breaker_trips_total',
    help: 'Intake batches failed instead of dead-lettered, because too much of the batch could not parse.',
    labelNames: ['kind'] as const,
})

export type IntakeBatchServices = {
    cyclotron: Pick<CyclotronV2Manager, 'createJobsIdempotently'>
    deadLetters: Pick<CdpDeadLetterService, 'recordMessageFailure' | 'produceForBatch'>
    invocationResults: Pick<
        HogInvocationResultsService,
        'prepareLifecycleRow' | 'queuePreparedRow' | 'handOffQueuedRows'
    >
    emailStatus: Pick<EmailStatusService, 'queue' | 'flush'>
}

export type IntakeBatchOptions = {
    kind: RunKind
    claimRetry: { initialDelayMs: number; maxElapsedMs: number }
}

type IntakeRun = {
    message: IntakeMessage
    invocation: CyclotronJobInvocation & { hogFlow: HogFlow }
    producedAt: number | undefined
}

// A shadow copy repeats a run the route already inserted and claimed. Once the claim can have expired with its job,
// inserting the copy would run it a second time, so an older copy is skipped. Topic retention keeps copies younger.
export const SHADOW_COPY_MAX_AGE_MS = IDEMPOTENCY_KEY_TTL_MS - 4 * 60 * 60 * 1000

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
    const { runs: parsed, unparseable } = parse(messages)
    const runs = firstOfEachRun(parsed, options.kind).filter((run) => !isExpiredShadowCopy(run, options.kind))

    // Dead letters are recorded only after the claim commits, so a batch that fails at the claim leaves nothing for its
    // retry to park twice.
    await claimRuns(runs, services, options)
    // Before the dead letters, so a failure there cannot leave the rows of committed runs queued for a redelivery to drop.
    const { produced } = await services.invocationResults.handOffQueuedRows()
    await Promise.all([produced, services.emailStatus.flush()])

    unparseable.forEach(({ source, reason }) => deadLetter(source, reason, services.deadLetters, options.kind))
    try {
        await services.deadLetters.produceForBatch(messages)
    } catch (error) {
        if (error instanceof DeadLetterCircuitBreakerError) {
            breakerTripsCounter.labels({ kind: options.kind }).inc()
        }
        throw error
    }
}

function parse(messages: Message[]): {
    runs: IntakeRun[]
    unparseable: { source: Message; reason: IntakeDeadLetterReason }[]
} {
    const runs: IntakeRun[] = []
    const unparseable: { source: Message; reason: IntakeDeadLetterReason }[] = []
    for (const source of messages) {
        const decoded = decodeIntakeMessage(source.value)
        if (decoded.status === 'decoded') {
            runs.push({
                message: decoded.message,
                invocation: intakeInvocation(decoded.message),
                producedAt: source.timestamp,
            })
        } else {
            unparseable.push({ source, reason: decoded.reason })
        }
    }
    return { runs, unparseable }
}

function deadLetter(
    source: Message,
    reason: IntakeDeadLetterReason,
    deadLetters: IntakeBatchServices['deadLetters'],
    kind: RunKind
): void {
    if (!deadLetters.recordMessageFailure(source, { step: 'parse', error: reason })) {
        throw new Error(
            `Intake message at ${source.topic}[${source.partition}]@${source.offset} is ${reason} and ` +
                'dead letters are off, so the batch fails rather than skip it'
        )
    }
    deadLettersCounter.labels({ kind, reason }).inc()
    logger.warn('[CdpIntake] Dead-lettered an intake message that can never insert', {
        kind,
        topic: source.topic,
        partition: source.partition,
        offset: source.offset,
        reason,
    })
}

function isExpiredShadowCopy(run: IntakeRun, kind: RunKind): boolean {
    if (!run.message.shadow || run.producedAt === undefined || Date.now() - run.producedAt <= SHADOW_COPY_MAX_AGE_MS) {
        return false
    }
    claimsCounter.labels({ kind, outcome: 'shadow_expired' }).inc()
    return true
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

async function claimRuns(runs: IntakeRun[], services: IntakeBatchServices, options: IntakeBatchOptions): Promise<void> {
    if (runs.length === 0) {
        return
    }
    // Prepared before the claim, as Run intake does: the running row stamps firstScheduledAt on the state, which the
    // job must store, and its version must come before a worker that finishes the job first.
    const runningRows = runs.map((run) => services.invocationResults.prepareLifecycleRow(run.invocation, 'running'))
    const outcomes = await claimWithRetry(
        runs.map((run) => ({
            job: intakeJobInit(run.message),
            fingerprint: claimFingerprint(run.message.job.id, run.message.fingerprint),
        })),
        services.cyclotron,
        options
    )

    runs.forEach((run, i) => {
        claimsCounter.labels({ kind: options.kind, outcome: outcomes[i] }).inc()
        if (outcomes[i] === 'created') {
            services.invocationResults.queuePreparedRow(runningRows[i])
            if (run.message.kind === 'transactional-email') {
                queueSend(run, services.emailStatus)
            }
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

function claimWithRetry(
    inputs: Parameters<IntakeBatchServices['cyclotron']['createJobsIdempotently']>[0],
    cyclotron: IntakeBatchServices['cyclotron'],
    { kind, claimRetry }: IntakeBatchOptions
): Promise<CyclotronV2IdempotentOutcome[]> {
    return retryIfRetriable(
        () =>
            cyclotron.createJobsIdempotently(inputs).catch((error: unknown) => {
                claimErrorsCounter.labels({ kind }).inc()
                logger.warn('[CdpIntake] An intake claim hit a cyclotron Postgres error', {
                    kind,
                    runs: inputs.length,
                    error: error instanceof Error ? error.message : String(error),
                })
                throw error
            }),
        {
            tries: Number.POSITIVE_INFINITY,
            sleepMs: claimRetry.initialDelayMs,
            softDeadlineMs: claimRetry.maxElapsedMs,
        }
    )
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
        messageCreatedAt: messageCreatedAtOf(
            (message.job.state?.state as Partial<HogFlowInvocationContext> | null)?.event
        ),
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
