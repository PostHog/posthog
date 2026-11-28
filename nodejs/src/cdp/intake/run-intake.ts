import { Counter } from 'prom-client'
import { v5 as uuidv5 } from 'uuid'

import { IdempotentJobQueue } from '~/cdp/services/job-queue/job-queue.interface'
import { CyclotronJobInvocationHogFlow } from '~/cdp/types'
import { logger } from '~/common/utils/logger'

import { IntakeProduceOutcome, IntakeProducer, IntakeRun, PublishSettlement } from './intake-producer'
import { RunKind } from './message'

export type Run = {
    kind: RunKind
    invocation: CyclotronJobInvocationHogFlow
    claim?: { fingerprint: string; reply?: Record<string, unknown> }
}

export type Claim = { runId: string; fingerprint: string }

export type Recalled =
    | { status: 'absent' }
    | {
          status: 'replayed' | 'mismatch'
          runId: string
          claimedFingerprint: string
          reply: Record<string, unknown> | null
      }

export type Produced = 'accepted' | 'unavailable' | 'too_large' | 'invalid'

const producedOf = (outcome: IntakeProduceOutcome): Produced =>
    outcome === 'acked' ? 'accepted' : outcome === 'unacked' ? 'unavailable' : outcome

const intakeRunOf = (run: Run): IntakeRun => ({
    kind: run.kind,
    invocation: run.invocation,
    fingerprint: run.claim?.fingerprint,
    reply: run.claim?.reply,
})

// A slow claim lookup must not hold up the answer: the consumer deduplicates anyway.
export const ASYNC_RECALL_BUDGET_MS = 250

const recallFailSoftCounter = new Counter({
    name: 'cdp_intake_recall_fail_soft_total',
    help: 'Claim lookups that failed or ran past their budget, so the run was produced without them, by kind.',
    labelNames: ['kind'] as const,
})

export type RunIntakeDeps = {
    hogflowQueue: Pick<IdempotentJobQueue, 'findIdempotencyKeys'>
    producer: IntakeProducer
}

// Never change the namespace or the name's encoding: a retry inside the claim's window would get another id and
// send a second time.
const KEYED_RUN_ID_NAMESPACE = 'c2b7f0a4-4c3e-4b8e-9d4f-6a1f3e5d2b90'

export const keyedRunId = (teamId: number, scope: string, key: string): string =>
    uuidv5(JSON.stringify([teamId, scope, key]), KEYED_RUN_ID_NAMESPACE)

const recalledOf = (
    { runId, fingerprint }: Claim,
    claimed: { fingerprint: string; reply: Record<string, unknown> | null } | null
): Recalled =>
    claimed === null
        ? { status: 'absent' }
        : {
              status: claimed.fingerprint === fingerprint ? 'replayed' : 'mismatch',
              runId,
              claimedFingerprint: claimed.fingerprint,
              reply: claimed.reply,
          }

export class RunIntake {
    constructor(private deps: RunIntakeDeps) {}

    // The claim is left to the consumer. Never throws; a lookup that fails or runs late reads as absent.
    async recallWithin(claim: Claim, kind: RunKind, budgetMs: number = ASYNC_RECALL_BUDGET_MS): Promise<Recalled> {
        return (await this.recallAllWithin([claim], kind, budgetMs))[0]
    }

    async recallAllWithin(
        claims: Claim[],
        kind: RunKind,
        budgetMs: number = ASYNC_RECALL_BUDGET_MS
    ): Promise<Recalled[]> {
        if (claims.length === 0) {
            return []
        }
        let timer: NodeJS.Timeout | undefined
        const late = new Promise<'late'>((resolve) => (timer = setTimeout(() => resolve('late'), budgetMs)))
        try {
            const found = await Promise.race([
                this.deps.hogflowQueue.findIdempotencyKeys(claims.map((claim) => claim.runId)),
                late,
            ])
            if (found !== 'late') {
                return claims.map((claim, i) => recalledOf(claim, found[i]))
            }
        } catch (error) {
            for (const claim of claims) {
                logger.warn('[CdpIntake] Claim lookup failed, producing the run without it', {
                    kind,
                    run_id: claim.runId,
                    error: error instanceof Error ? error.message : String(error),
                })
            }
        } finally {
            clearTimeout(timer)
        }
        recallFailSoftCounter.labels({ kind }).inc(claims.length)
        return claims.map(() => ({ status: 'absent' }))
    }

    async produce(run: Run, settlement?: PublishSettlement): Promise<Produced> {
        return producedOf(await this.deps.producer.produce(intakeRunOf(run), settlement))
    }

    // Publishes none of the runs when encoding them all ends past `publishBy`, a `performance.now()` time.
    async produceAllBy(runs: Run[], publishBy: number): Promise<Produced[] | 'deadline_exceeded'> {
        const producer = this.deps.producer
        const encoded = runs.map((run) => producer.encode(intakeRunOf(run)))
        if (performance.now() > publishBy) {
            return 'deadline_exceeded'
        }
        return Promise.all(
            encoded.map(async (run) => producedOf(typeof run === 'string' ? run : await producer.publish(run)))
        )
    }
}
