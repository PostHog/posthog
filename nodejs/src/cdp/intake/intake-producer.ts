import { Counter, Histogram } from 'prom-client'

import { buildIntegerMatcher } from '~/common/config/matchers'
import { IngestionOutputs } from '~/common/outputs/ingestion-outputs'
import { logger } from '~/common/utils/logger'

import { CdpConfig } from '../config'
import {
    CDP_INTAKE_MSK_TRANSACTIONAL_EMAIL_OUTPUT,
    CDP_INTAKE_MSK_WORKFLOW_WEBHOOK_OUTPUT,
    CDP_INTAKE_TRANSACTIONAL_EMAIL_OUTPUT,
    CDP_INTAKE_WORKFLOW_WEBHOOK_OUTPUT,
    CdpIntakeRunOutput,
} from '../outputs/outputs'
import { KafkaMskCdpIntakeProducerEnvConfig } from '../outputs/producers'
import { encodeJob } from '../services/cyclotron-v2/job-codec'
import { CyclotronJobInvocation } from '../types'
import { RunKind, encodeIntakeMessage } from './message'

export type IntakeMode = 'off' | 'shadow' | 'async'
export type IntakeCluster = 'warpstream' | 'msk'
export type IntakeOutput = CdpIntakeRunOutput
export type IntakeProduceOutcome = 'acked' | 'unacked' | 'too_large' | 'invalid'

// A route answers once the broker acks, or after this long without one.
export const INTAKE_ACK_DEADLINE_MS = 3_000

const OUTPUT_OF: Record<IntakeCluster, Record<RunKind, IntakeOutput>> = {
    warpstream: {
        'transactional-email': CDP_INTAKE_TRANSACTIONAL_EMAIL_OUTPUT,
        'workflow-webhook': CDP_INTAKE_WORKFLOW_WEBHOOK_OUTPUT,
    },
    msk: {
        'transactional-email': CDP_INTAKE_MSK_TRANSACTIONAL_EMAIL_OUTPUT,
        'workflow-webhook': CDP_INTAKE_MSK_WORKFLOW_WEBHOOK_OUTPUT,
    },
}

const launchesCounter = new Counter({
    name: 'cdp_intake_launches_total',
    help: 'Runs the routes produced to an intake topic, by kind, mode and outcome: acked by the broker, unacked (refused, or no ack before the deadline), too_large for the topic, or invalid for the cyclotron row.',
    labelNames: ['kind', 'mode', 'outcome', 'cluster'] as const,
})

const ackMs = new Histogram({
    name: 'cdp_intake_ack_ms',
    help: "Milliseconds from producing an accepted run to an intake topic to the broker's ack, by kind and cluster.",
    labelNames: ['kind', 'cluster'] as const,
    buckets: [5, 10, 25, 50, 100, 250, 500, 1_000, 2_500, 3_000],
})

export const intakeModeOf = (
    config: Pick<CdpConfig, 'CDP_INTAKE_KAFKA_SHADOW_TEAMS' | 'CDP_INTAKE_KAFKA_ASYNC_TEAMS'>
): ((teamId: number) => IntakeMode) => {
    const isAsync = buildIntegerMatcher(config.CDP_INTAKE_KAFKA_ASYNC_TEAMS, true)
    const isShadow = buildIntegerMatcher(config.CDP_INTAKE_KAFKA_SHADOW_TEAMS, true)
    return (teamId) => (isAsync(teamId) ? 'async' : isShadow(teamId) ? 'shadow' : 'off')
}

export const intakeClusterOf = (
    config: Pick<CdpConfig, 'CDP_INTAKE_MSK_TEAMS'> &
        Pick<KafkaMskCdpIntakeProducerEnvConfig, 'KAFKA_MSK_CDP_INTAKE_PRODUCER_METADATA_BROKER_LIST'>
): ((teamId: number) => IntakeCluster) => {
    // Without MSK brokers the MSK producer opens WarpStream's config, so the list must not route there.
    const onMsk = buildIntegerMatcher(
        config.KAFKA_MSK_CDP_INTAKE_PRODUCER_METADATA_BROKER_LIST ? config.CDP_INTAKE_MSK_TEAMS : '',
        true
    )
    return (teamId) => (onMsk(teamId) ? 'msk' : 'warpstream')
}

// A produce outlives its ack deadline. A caller that bounds its work in flight passes a settlement to its produces and,
// after they return, waits on `publishesSettled()` with the same handle before it frees that work's share. The unread
// private field makes the type nominal, so neither a plain object nor a spread copy type-checks as a settlement.
export class PublishSettlement {
    readonly #brand = true
}

const trackedPublishes = new WeakMap<PublishSettlement, Promise<unknown>[]>()

const trackPublish = (settlement: PublishSettlement, publish: Promise<unknown>): void => {
    const publishes = trackedPublishes.get(settlement)
    if (publishes) {
        publishes.push(publish)
    } else {
        trackedPublishes.set(settlement, [publish])
    }
}

export const publishesSettled = (settlement: PublishSettlement): Promise<void> =>
    Promise.allSettled(trackedPublishes.get(settlement) ?? []).then(() => undefined)

export type IntakeRun = {
    kind: RunKind
    invocation: CyclotronJobInvocation
    fingerprint?: string
    reply?: Record<string, unknown>
}

export class IntakeProducer {
    constructor(
        private outputs: IngestionOutputs<IntakeOutput>,
        private ackDeadlineMs: number = INTAKE_ACK_DEADLINE_MS,
        // Encrypts a transactional send's content before it reaches the topic, as the job queues do.
        private seal: (invocation: CyclotronJobInvocation) => CyclotronJobInvocation = (invocation) => invocation,
        private clusterOf: (teamId: number) => IntakeCluster = () => 'warpstream'
    ) {}

    async produce(
        { kind, invocation, fingerprint, reply }: IntakeRun,
        mode: IntakeMode,
        settlement?: PublishSettlement
    ): Promise<IntakeProduceOutcome> {
        const cluster = this.clusterOf(invocation.teamId)
        const encoded = encodeIntakeMessage({
            kind,
            fingerprint,
            reply,
            shadow: mode === 'shadow',
            job: { ...encodeJob(this.seal(invocation)), id: invocation.id },
        })
        if (encoded.status !== 'encoded') {
            launchesCounter.labels({ kind, mode, outcome: encoded.status, cluster }).inc()
            return encoded.status
        }
        const startedAt = performance.now()
        try {
            await this.withinDeadline(this.outputs.produce(OUTPUT_OF[cluster][kind], encoded.message), settlement)
            ackMs.labels({ kind, cluster }).observe(performance.now() - startedAt)
            launchesCounter.labels({ kind, mode, outcome: 'acked', cluster }).inc()
            return 'acked'
        } catch (error) {
            launchesCounter.labels({ kind, mode, outcome: 'unacked', cluster }).inc()
            logger.warn('[CdpIntake] An intake produce got no ack', {
                kind,
                cluster,
                team_id: invocation.teamId,
                run_id: invocation.id,
                error: error instanceof Error ? error.message : String(error),
            })
            return 'unacked'
        }
    }

    // The produce keeps running after the deadline, so a late ack can still land the message: an unacked run is
    // unconfirmed, not lost.
    private withinDeadline(produce: Promise<void>, settlement?: PublishSettlement): Promise<void> {
        let timer: NodeJS.Timeout | undefined
        const deadline = new Promise<never>((_, reject) => {
            timer = setTimeout(() => reject(new Error('no ack before the deadline')), this.ackDeadlineMs)
        })
        const raced = Promise.race([produce, deadline]).finally(() => clearTimeout(timer))
        if (settlement) {
            trackPublish(settlement, produce)
        }
        return raced
    }
}
