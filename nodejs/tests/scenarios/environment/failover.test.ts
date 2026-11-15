import { randomUUID } from 'crypto'

import { FakeCloud, FakeCloudOptions } from '../cloud/fake-cloud'
import type { Manifest } from '../cloud/lease'
import type { WriterSample } from '../probe/writer-probe'
import { createEnvironment } from './environment'
import { FailoverOptions, failOver } from './failover'

const HOLD_MS = 30 * 60_000
const OBSERVE_WITHIN_MS = 400
const IDLE = { liveReaderAcu: { maxima: [1, 1, 1, 1, 1] } }

type Run = { cloud: FakeCloud; manifest: Manifest; cluster: string; writer: string; reader: string }

function runOf(options: Partial<FakeCloudOptions> = {}): Run {
    const cloud = new FakeCloud({ now: () => new Date(), failover: { takesMs: 20 }, ...IDLE, ...options })
    const runId = randomUUID()
    const { cluster, writer, reader } = cloud.runCluster(runId)
    const manifest: Manifest = {
        runId,
        owner: 'arn:aws:sts::000000000000:assumed-role/scenario-run-controller/person',
        account: cloud.account,
        region: 'us-east-1',
        commit: '0'.repeat(40),
        createdAt: new Date().toISOString(),
        expiresAt: new Date(Date.now() + 6 * 60 * 60_000).toISOString(),
        stackName: cluster,
        schedules: [],
        inputs: {},
    }
    return { cloud, manifest, cluster, writer, reader }
}

const probeThroughPooler = ({ cloud, cluster }: Run): (() => WriterSample[]) => {
    const samples: WriterSample[] = []
    return () => {
        samples.push({ at: Date.now(), monoMs: 0, ok: true, latencyMs: 0, instance: cloud.writerOf(cluster) })
        return samples
    }
}

const failOverOn = (run: Run, overrides: Partial<FailoverOptions> = {}) =>
    failOver({
        aws: run.cloud,
        manifest: run.manifest,
        holdMs: HOLD_MS,
        identity: () => Promise.resolve({ instance: run.cloud.writerOf(run.cluster)!, inRecovery: false }),
        commits: probeThroughPooler(run),
        pollMs: 5,
        observeWithinMs: OBSERVE_WITHIN_MS,
        ...overrides,
    })

const OBSERVED = [
    { name: 'cluster_writer', at: expect.any(String) },
    { name: 'sql_writer', at: expect.any(String) },
    { name: 'first_probe_commit', at: expect.any(String) },
]

describe('pg.failover', () => {
    it.each<[string, Partial<FakeCloudOptions>, (run: Run) => void, RegExp]>([
        [
            'a caller outside the run account',
            {},
            (run) => (run.manifest.account = '111111111111'),
            /the caller is in account 000000000000, not the run's account 111111111111/,
        ],
        [
            'a lease shorter than the hold and the fail-back',
            {},
            (run) => (run.manifest.expiresAt = new Date(Date.now() + HOLD_MS).toISOString()),
            /the lease has \d+s left, under the 1800\.4s/,
        ],
        [
            'a cluster tagged for another run',
            {},
            (run) => (run.cloud.resources.find(({ id }) => id === run.cluster)!.runTag = randomUUID()),
            /does not carry scenario-run=/,
        ],
        [
            'a cluster that is not available',
            {},
            (run) => (run.cloud.resources.find(({ id }) => id === run.cluster)!.state = 'backing-up'),
            /is backing-up, not available/,
        ],
        [
            'a cluster with a member the manifest does not name',
            {},
            (run) => {
                const reader = run.cloud.resources.find(({ id }) => id === run.reader)!
                run.cloud.resources.push({ ...reader, id: `${run.reader}-2` })
            },
            /has members .*-reader, .*-reader-2, .*-writer/,
        ],
        [
            'a cluster whose reader already writes',
            {},
            (run) => (run.cloud.resources.find(({ id }) => id === run.cluster)!.writer = run.reader),
            /with writer .*-reader, not .*-writer writing beside/,
        ],
        [
            'a reader at 2 ACU in its last five minutes',
            { liveReaderAcu: { maxima: [1, 1, 2, 1, 1] } },
            () => undefined,
            /was above 1 ACU in its last 5 minutes: 2 at /,
        ],
        [
            'a reader with fewer than five capacity minutes',
            { liveReaderAcu: { maxima: [1, 1, 1, 1] } },
            () => undefined,
            /has 4 complete capacity minutes, under the 5 it needs/,
        ],
        [
            'a reader whose newest capacity minute is over three minutes old',
            { liveReaderAcu: { maxima: [1, 1, 1, 1, 1], lagMinutes: 4 } },
            () => undefined,
            /newest capacity minute ended \d+s ago/,
        ],
    ])('refuses before any request on %s', async (_story, options, arrange, reason) => {
        const run = runOf(options)
        arrange(run)

        await expect(failOverOn(run)).rejects.toThrow(new RegExp(`^pg.failover refused: .*${reason.source}`))
        expect(run.cloud.promotions).toEqual([])
    })

    it('promotes the reader, observes each recovery stage, then fails back to the original writer', async () => {
        const run = runOf()

        const actuation = await failOverOn(run)
        await expect(actuation.observed()).resolves.toBe(true)
        expect(run.cloud.writerOf(run.cluster)).toBe(run.reader)
        await actuation.release()

        expect(run.cloud.writerOf(run.cluster)).toBe(run.writer)
        expect(run.cloud.promotions.map(({ to }) => to)).toEqual([run.reader, run.writer])
        expect(actuation.journal()).toEqual({
            intentAt: expect.any(String),
            observations: OBSERVED,
            releaseIntentAt: expect.any(String),
            releaseObservations: OBSERVED,
        })
    })

    it('counts no probe commit that still lands on the old writer', async () => {
        const run = runOf()
        const onOldWriter: WriterSample[] = []
        const commits = (): WriterSample[] => {
            onOldWriter.push({ at: Date.now(), monoMs: 0, ok: true, latencyMs: 0, instance: run.writer })
            return onOldWriter
        }

        const actuation = await failOverOn(run, { commits })

        await expect(actuation.observed()).resolves.toBe(false)
        expect(actuation.journal()).toMatchObject({
            observations: OBSERVED.slice(0, 2),
            unobserved: expect.stringMatching(/-reader did not show first_probe_commit within 0.4s/),
        })
    })

    it.each<[string, number, boolean, string | undefined]>([
        ['observes a promotion whose response was lost', 20, true, undefined],
        [
            'leaves a lost response that never promotes unobserved',
            Infinity,
            false,
            'failover request ambiguous, not observed: aws rds failover-db-cluster exited 255',
        ],
    ])('%s, sending the request once', async (_story, takesMs, observed, unobserved) => {
        const run = runOf({ failover: { takesMs } })
        run.cloud.loseResponseOf('failover-db-cluster')

        const actuation = await failOverOn(run)

        await expect(actuation.observed()).resolves.toBe(observed)
        expect(run.cloud.promotions).toHaveLength(1)
        expect(actuation.journal().unobserved).toEqual(unobserved && expect.stringContaining(unobserved))
    })

    it('records a refused fail-back instead of throwing it', async () => {
        const run = runOf()
        const actuation = await failOverOn(run)
        await actuation.observed()
        run.cloud.failWhen('failover-db-cluster', (args) => args.includes(run.writer))

        await actuation.release()

        expect(run.cloud.writerOf(run.cluster)).toBe(run.reader)
        expect(actuation.journal()).toMatchObject({
            releaseIntentAt: expect.any(String),
            releaseError: expect.stringMatching(/^the fail-back request was refused: .*InternalFailure/),
        })
    })

    it('runs only on a run host', async () => {
        const environment = createEnvironment({ aws: runOf().cloud })

        await expect(environment.actuate({ kind: 'rds.failover', holdMs: HOLD_MS, commits: () => [] })).rejects.toThrow(
            'pg.failover runs only on a run host'
        )
    })
})
