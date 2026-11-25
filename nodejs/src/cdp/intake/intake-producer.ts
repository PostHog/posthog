import { Counter, Histogram } from 'prom-client'

import { IngestionOutputs } from '~/common/outputs/ingestion-outputs'
import { logger } from '~/common/utils/logger'

import {
    CDP_INTAKE_MSK_TRANSACTIONAL_EMAIL_OUTPUT,
    CDP_INTAKE_MSK_WORKFLOW_WEBHOOK_OUTPUT,
    CdpIntakeRunOutput,
} from '../outputs/outputs'
import { KafkaMskCdpIntakeProducerEnvConfig } from '../outputs/producers'
import { encodeJob } from '../services/cyclotron-v2/job-codec'
import { CyclotronJobInvocation } from '../types'
import { EncodedIntakeMessage, RunKind, encodeIntakeMessage } from './message'

export type IntakeCluster = 'msk' | 'warpstream'
export type IntakeOutput = CdpIntakeRunOutput
export type IntakeProduceOutcome = 'acked' | 'unacked' | 'too_large' | 'invalid'

// Every run is produced now. The label stays, because alerts and dashboards group by it.
const INTAKE_MODE = 'async'

// A route answers once the broker acks, or after this long without one.
export const INTAKE_ACK_DEADLINE_MS = 3_000

const OUTPUT_OF: Record<RunKind, IntakeOutput> = {
    'transactional-email': CDP_INTAKE_MSK_TRANSACTIONAL_EMAIL_OUTPUT,
    'workflow-webhook': CDP_INTAKE_MSK_WORKFLOW_WEBHOOK_OUTPUT,
}

// Alerts and dashboards filter the metrics below on this label. Without MSK brokers the MSK producer opens WarpStream's
// config, so the label names the cluster the runs reach.
export const intakeClusterOf = (
    config: Pick<KafkaMskCdpIntakeProducerEnvConfig, 'KAFKA_MSK_CDP_INTAKE_PRODUCER_METADATA_BROKER_LIST'>
): IntakeCluster => (config.KAFKA_MSK_CDP_INTAKE_PRODUCER_METADATA_BROKER_LIST ? 'msk' : 'warpstream')

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

export type EncodedIntakeRun = {
    kind: RunKind
    cluster: IntakeCluster
    teamId: number
    runId: string
    message: EncodedIntakeMessage
}

export class IntakeProducer {
    constructor(
        private outputs: IngestionOutputs<IntakeOutput>,
        private ackDeadlineMs: number = INTAKE_ACK_DEADLINE_MS,
        // Encrypts a transactional send's content before it reaches the topic, as the job queues do.
        private seal: (invocation: CyclotronJobInvocation) => CyclotronJobInvocation = (invocation) => invocation,
        private cluster: IntakeCluster = 'msk'
    ) {}

    async produce(run: IntakeRun, settlement?: PublishSettlement): Promise<IntakeProduceOutcome> {
        const encoded = this.encode(run)
        return typeof encoded === 'string' ? encoded : this.publish(encoded, settlement)
    }

    // Encoding seals and serializes on the event loop, so a caller with a deadline encodes all its runs, checks its
    // clock, and only then publishes them.
    encode({ kind, invocation, fingerprint, reply }: IntakeRun): EncodedIntakeRun | 'too_large' | 'invalid' {
        const cluster = this.cluster
        const encoded = encodeIntakeMessage({
            kind,
            fingerprint,
            reply,
            job: { ...encodeJob(this.seal(invocation)), id: invocation.id },
        })
        if (encoded.status !== 'encoded') {
            launchesCounter.labels({ kind, mode: INTAKE_MODE, outcome: encoded.status, cluster }).inc()
            return encoded.status
        }
        return { kind, cluster, teamId: invocation.teamId, runId: invocation.id, message: encoded.message }
    }

    async publish(
        { kind, cluster, teamId, runId, message }: EncodedIntakeRun,
        settlement?: PublishSettlement
    ): Promise<'acked' | 'unacked'> {
        const startedAt = performance.now()
        try {
            await this.withinDeadline(this.outputs.produce(OUTPUT_OF[kind], message), settlement)
            ackMs.labels({ kind, cluster }).observe(performance.now() - startedAt)
            launchesCounter.labels({ kind, mode: INTAKE_MODE, outcome: 'acked', cluster }).inc()
            return 'acked'
        } catch (error) {
            launchesCounter.labels({ kind, mode: INTAKE_MODE, outcome: 'unacked', cluster }).inc()
            logger.warn('[CdpIntake] An intake produce got no ack', {
                kind,
                cluster,
                team_id: teamId,
                run_id: runId,
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
