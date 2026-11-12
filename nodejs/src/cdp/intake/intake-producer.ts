import { Counter, Histogram } from 'prom-client'

import { buildIntegerMatcher } from '~/common/config/matchers'
import { IngestionOutputs } from '~/common/outputs/ingestion-outputs'
import { logger } from '~/common/utils/logger'

import { CdpConfig } from '../config'
import {
    CDP_INTAKE_TRANSACTIONAL_EMAIL_OUTPUT,
    CDP_INTAKE_WORKFLOW_WEBHOOK_OUTPUT,
    CdpIntakeRunOutput,
} from '../outputs/outputs'
import { encodeJob } from '../services/cyclotron-v2/job-codec'
import { CyclotronJobInvocation } from '../types'
import { RunKind, encodeIntakeMessage } from './message'

export type IntakeMode = 'off' | 'shadow' | 'async'
export type IntakeOutput = CdpIntakeRunOutput
export type IntakeProduceOutcome = 'acked' | 'unacked' | 'too_large' | 'invalid'

// A route answers once the broker acks, or after this long without one.
export const INTAKE_ACK_DEADLINE_MS = 3_000

const OUTPUT_OF: Record<RunKind, IntakeOutput> = {
    'transactional-email': CDP_INTAKE_TRANSACTIONAL_EMAIL_OUTPUT,
    'workflow-webhook': CDP_INTAKE_WORKFLOW_WEBHOOK_OUTPUT,
}

const launchesCounter = new Counter({
    name: 'cdp_intake_launches_total',
    help: 'Runs the routes produced to an intake topic, by kind, mode and outcome: acked by the broker, unacked (refused, or no ack before the deadline), too_large for the topic, or invalid for the cyclotron row.',
    labelNames: ['kind', 'mode', 'outcome'] as const,
})

const ackMs = new Histogram({
    name: 'cdp_intake_ack_ms',
    help: "Milliseconds from producing an accepted run to an intake topic to the broker's ack, by kind.",
    labelNames: ['kind'] as const,
    buckets: [5, 10, 25, 50, 100, 250, 500, 1_000, 2_500, 3_000],
})

export const intakeModeOf = (
    config: Pick<CdpConfig, 'CDP_INTAKE_KAFKA_SHADOW_TEAMS' | 'CDP_INTAKE_KAFKA_ASYNC_TEAMS'>
): ((teamId: number) => IntakeMode) => {
    const isAsync = buildIntegerMatcher(config.CDP_INTAKE_KAFKA_ASYNC_TEAMS, true)
    const isShadow = buildIntegerMatcher(config.CDP_INTAKE_KAFKA_SHADOW_TEAMS, true)
    return (teamId) => (isAsync(teamId) ? 'async' : isShadow(teamId) ? 'shadow' : 'off')
}

export type IntakeRun = { kind: RunKind; invocation: CyclotronJobInvocation; fingerprint?: string }

export class IntakeProducer {
    constructor(
        private outputs: IngestionOutputs<IntakeOutput>,
        private ackDeadlineMs: number = INTAKE_ACK_DEADLINE_MS
    ) {}

    async produce({ kind, invocation, fingerprint }: IntakeRun, mode: IntakeMode): Promise<IntakeProduceOutcome> {
        const encoded = encodeIntakeMessage({ kind, fingerprint, job: { ...encodeJob(invocation), id: invocation.id } })
        if (encoded.status !== 'encoded') {
            launchesCounter.labels({ kind, mode, outcome: encoded.status }).inc()
            return encoded.status
        }
        const startedAt = performance.now()
        try {
            await this.withinDeadline(this.outputs.produce(OUTPUT_OF[kind], encoded.message))
            ackMs.labels({ kind }).observe(performance.now() - startedAt)
            launchesCounter.labels({ kind, mode, outcome: 'acked' }).inc()
            return 'acked'
        } catch (error) {
            launchesCounter.labels({ kind, mode, outcome: 'unacked' }).inc()
            logger.warn('[CdpIntake] An intake produce got no ack', {
                kind,
                team_id: invocation.teamId,
                run_id: invocation.id,
                error: error instanceof Error ? error.message : String(error),
            })
            return 'unacked'
        }
    }

    // The produce keeps running after the deadline, so a late ack can still land the message: an unacked run is
    // unconfirmed, not lost.
    private withinDeadline(produce: Promise<void>): Promise<void> {
        let timer: NodeJS.Timeout | undefined
        const deadline = new Promise<never>((_, reject) => {
            timer = setTimeout(() => reject(new Error('no ack before the deadline')), this.ackDeadlineMs)
        })
        produce.catch(() => undefined)
        return Promise.race([produce, deadline]).finally(() => clearTimeout(timer))
    }
}
