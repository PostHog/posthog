import { v5 as uuidv5 } from 'uuid'

import { CyclotronV2IdempotentClaim } from '~/cdp/services/cyclotron-v2/types'
import { IdempotentJobQueue } from '~/cdp/services/job-queue/job-queue.interface'
import { HogInvocationResultsService } from '~/cdp/services/monitoring/hog-invocation-results.service'
import { CyclotronJobInvocationHogFlow } from '~/cdp/types'

import { IntakeMode, IntakeProducer } from './intake-producer'
import { RunKind, claimFingerprint } from './message'

export type Run = {
    kind: RunKind
    invocation: CyclotronJobInvocationHogFlow
    claim?: { fingerprint: string }
}

export type Claim = { runId: string; fingerprint: string }

export type Recalled =
    | { status: 'absent' }
    | { status: 'replayed' | 'mismatch'; runId: string; claimedFingerprint: string }

// `claimedFingerprint` is set when a keyed run found an existing claim: the fingerprint of the request that made it.
export type Committed = { runId: string; outcome: CyclotronV2IdempotentClaim['outcome']; claimedFingerprint?: string }

export type RunIntakeDeps = {
    hogflowQueue: Pick<IdempotentJobQueue, 'queueInvocations' | 'queueInvocationsIdempotently' | 'findIdempotencyKey'>
    invocationResultsRowsService: HogInvocationResultsService
    // Absent, or `off` for a team, means the run never touches the intake topics.
    intake?: { modeOf: (teamId: number) => IntakeMode; producer: IntakeProducer }
}

// Never change the namespace or the name's encoding: a retry inside the claim's window would get another id and
// send a second time.
const KEYED_RUN_ID_NAMESPACE = 'c2b7f0a4-4c3e-4b8e-9d4f-6a1f3e5d2b90'

export const keyedRunId = (teamId: number, scope: string, key: string): string =>
    uuidv5(JSON.stringify([teamId, scope, key]), KEYED_RUN_ID_NAMESPACE)

export class RunIntake {
    constructor(private deps: RunIntakeDeps) {}

    async recall({ runId, fingerprint }: Claim): Promise<Recalled> {
        const claimed = await this.deps.hogflowQueue.findIdempotencyKey(runId)
        if (claimed === null) {
            return { status: 'absent' }
        }
        return {
            status: claimed.fingerprint === fingerprint ? 'replayed' : 'mismatch',
            runId,
            claimedFingerprint: claimed.fingerprint,
        }
    }

    async launch(runs: Run[], _options: { wait: 'committed' }): Promise<Committed[]> {
        const invocations = runs.map((run) => run.invocation)
        const rows = this.deps.invocationResultsRowsService
        // Prepared before the insert: only a stamp set before serialization reaches cyclotron, and a worker can finish
        // the job before the insert returns, so a later version would outrank its terminal row.
        const runningRows = invocations.map((invocation) => rows.prepareLifecycleRow(invocation, 'running'))
        const claims = await this.insert(runs)
        // A repeat shares the created run's id, so only the created run's row is queued.
        runningRows.forEach((row, i) => {
            if (claims[i].outcome === 'created') {
                rows.queuePreparedRow(row)
            }
        })
        await this.produceShadowCopies(runs.filter((_, i) => claims[i].outcome === 'created'))
        return invocations.map((invocation, i) => ({
            runId: invocation.id,
            outcome: claims[i].outcome,
            claimedFingerprint: claims[i].storedFingerprint,
        }))
    }

    // Shadow measures the Kafka path beside the insert: the answer is already decided, so a failed produce changes nothing.
    private async produceShadowCopies(created: Run[]): Promise<void> {
        const intake = this.deps.intake
        const shadow = intake ? created.filter((run) => intake.modeOf(run.invocation.teamId) === 'shadow') : []
        await Promise.all(
            shadow.map((run) =>
                intake!.producer.produce(
                    { kind: run.kind, invocation: run.invocation, fingerprint: run.claim?.fingerprint },
                    'shadow'
                )
            )
        )
    }

    private async insert(runs: Run[]): Promise<CyclotronV2IdempotentClaim[]> {
        const claims: CyclotronV2IdempotentClaim[] = runs.map(() => ({ outcome: 'created' }))
        // A run that can reach the intake topic claims a row even without a key, so the consumer replays its copy.
        const claimOf = (run: Run): { fingerprint: string } | undefined =>
            run.claim ?? (this.onIntake(run) ? { fingerprint: claimFingerprint(run.invocation.id) } : undefined)
        const keyed = runs.flatMap((run, i) => {
            const claim = claimOf(run)
            return claim ? [{ i, fingerprint: claim.fingerprint }] : []
        })
        const keyless = runs.filter((run) => !claimOf(run)).map((run) => run.invocation)
        if (keyless.length > 0) {
            await this.deps.hogflowQueue.queueInvocations(keyless)
        }
        if (keyed.length > 0) {
            const claimed = await this.deps.hogflowQueue.queueInvocationsIdempotently(
                keyed.map(({ i, fingerprint }) => ({ invocation: runs[i].invocation, fingerprint }))
            )
            keyed.forEach(({ i }, k) => (claims[i] = claimed[k]))
        }
        return claims
    }

    private onIntake(run: Run): boolean {
        return (this.deps.intake?.modeOf(run.invocation.teamId) ?? 'off') !== 'off'
    }
}
