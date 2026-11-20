import { randomUUID } from 'crypto'
import { mkdtempDisposableSync, writeFileSync } from 'fs'
import { tmpdir } from 'os'
import path from 'path'
import { setTimeout as sleep } from 'timers/promises'

import { waitForExpect } from '~/tests/helpers/expectations'

import { Controller } from '../cloud/admission'
import type { Aws } from '../cloud/aws'
import { FakeCloud, FakeCloudOptions } from '../cloud/fake-cloud'
import { PROFILE, pinClockAfterMinuteStart } from '../cloud/fixtures'
import { RunManifest, keyOf, lease, runManifestOf } from '../cloud/lease'
import { CloudProfile } from '../cloud/profile'
import type { WriterSample } from '../probe/writer-probe'
import { FailoverActuation, FailoverOptions, SqlIdentity, failOver } from './failover'

const HOLD_MS = 30 * 60_000
const OBSERVE_WITHIN_MS = 400
const IDLE = { liveReaderAcu: { maxima: [1, 1, 1, 1, 1] } }

type Run = { cloud: FakeCloud; manifest: RunManifest; cluster: string; writer: string; reader: string; aws?: Aws }

function runOf(options: Partial<FakeCloudOptions> = {}): Run {
    const cloud = new FakeCloud({ now: () => new Date(), failover: { takesMs: 20 }, ...IDLE, ...options })
    return { cloud, ...cloud.runCluster(randomUUID()) }
}

const probeThroughPooler = ({ cloud, cluster }: Run): (() => WriterSample[]) => {
    const samples: WriterSample[] = []
    return () => {
        cloud.tick()
        samples.push({ at: Date.now(), monoMs: 0, ok: true, latencyMs: 0, instance: cloud.writerOf(cluster) })
        return samples
    }
}

const MINUTE_MS = 60_000

const flagOf = (args: string[], flag: string): string => args[args.indexOf(flag) + 1]

type CapacityAnswer = { ascending: boolean; until: number; minutes: number[] }

const answeringCapacity = (cloud: FakeCloud, answerOf: (asked: CapacityAnswer) => unknown): Aws => ({
    call: (args) => {
        if (args[1] !== 'get-metric-data') {
            return cloud.call(args)
        }
        const until = Date.parse(flagOf(args, '--end-time'))
        const ascending = flagOf(args, '--scan-by') === 'TimestampAscending'
        const minutes = [5, 4, 3, 2, 1].map((back) => until - back * MINUTE_MS)
        return Promise.resolve(answerOf({ ascending, until, minutes: ascending ? minutes : minutes.reverse() }))
    },
    text: (args) => cloud.text(args),
})

const idleAnswer = ({ minutes }: CapacityAnswer, fields: Record<string, unknown> = {}): unknown => ({
    Messages: [],
    MetricDataResults: [
        {
            Id: 'acu',
            Label: 'ServerlessDatabaseCapacity',
            Timestamps: minutes.map((at) => new Date(at).toISOString().replace('.000Z', '+00:00')),
            Values: minutes.map(() => 1),
            StatusCode: 'Complete',
            Messages: [],
            ...fields,
        },
    ],
})

const failOverOn = (run: Run, overrides: Partial<FailoverOptions> = {}) =>
    failOver({
        aws: run.aws ?? run.cloud,
        manifest: run.manifest,
        holdMs: HOLD_MS,
        identity: () => {
            run.cloud.tick()
            return Promise.resolve({ instance: run.cloud.writerOf(run.cluster)!, inRecovery: false })
        },
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
    beforeEach(() => {
        pinClockAfterMinuteStart()
    })

    afterEach(() => {
        jest.useRealTimers()
    })

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
            /the lease has \d+s left, under the 1800\.8s/,
        ],
        [
            'a lease that runs short during the precondition reads',
            {},
            (run) =>
                run.cloud.beforeCall(
                    'get-metric-data',
                    () => (run.manifest.expiresAt = new Date(Date.now() + HOLD_MS).toISOString())
                ),
            /the lease has \d+s left, under the 1800\.8s/,
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
            'a reader above the idle limit in its last five minutes',
            { liveReaderAcu: { maxima: [1, 1, 3, 1, 1] } },
            () => undefined,
            /was above its 2.5 ACU idle limit in its last 5 minutes: 3 at /,
        ],
        [
            'a reader above the lower idle limit its run manifest names',
            { liveReaderAcu: { maxima: [2, 2, 2, 2, 2] } },
            (run) => (run.manifest.readerIdleMaxAcu = 1.5),
            /was above its 1.5 ACU idle limit in its last 5 minutes: 2 at /,
        ],
        [
            'a capacity read with fewer values than timestamps',
            { shortValuesOf: 'Average' },
            () => undefined,
            /-reader's capacity read has 5 timestamps and 4 values/,
        ],
        [
            'a capacity read with a value that is not a finite number',
            { liveReaderAcu: { maxima: [1, 1, Number.NaN, 1, 1] } },
            () => undefined,
            /-reader's capacity read has a value that is not a finite number at /,
        ],
        [
            'a capacity read with no status',
            { liveReaderAcu: { maxima: [2, 2, 2, 2, 2] }, omitsCapacityStatus: true },
            () => undefined,
            /-reader's capacity read came back with no status, not Complete/,
        ],
        [
            'a capacity read with a timestamp that is not a time',
            { unknownTimestampOf: 'Average' },
            () => undefined,
            /-reader's capacity read has a timestamp that is not a time: unknown/,
        ],
        [
            'a capacity read in descending time order',
            {},
            (run) =>
                (run.aws = answeringCapacity(run.cloud, (asked) =>
                    idleAnswer({ ...asked, minutes: [...asked.minutes].sort((a, b) => b - a) })
                )),
            /-reader's capacity read is not in ascending time order at /,
        ],
        [
            'a capacity read with a minute after the window it asked for',
            {},
            (run) =>
                (run.aws = answeringCapacity(run.cloud, (asked) =>
                    idleAnswer({ ...asked, minutes: asked.minutes.map((at) => at + 5 * MINUTE_MS) })
                )),
            /-reader's capacity read has a timestamp outside the .* it asked for: /,
        ],
        [
            'a capacity read with a reading under the minimum its run manifest names before its last five minutes',
            { liveReaderAcu: { maxima: [1, 0, 1, 1, 1, 1, 1] } },
            () => undefined,
            /-reader's capacity read has a value below 1 at /,
        ],
        [
            'a capacity read whose minutes sit off the minute',
            {},
            (run) =>
                (run.aws = answeringCapacity(run.cloud, (asked) =>
                    idleAnswer({ ...asked, minutes: asked.minutes.map((at) => at + MINUTE_MS / 2) })
                )),
            /-reader's capacity read has a timestamp off the 60s period of its window: /,
        ],
        [
            'a capacity read whose times are finer than a millisecond',
            {},
            (run) =>
                (run.aws = answeringCapacity(run.cloud, (asked) =>
                    idleAnswer(asked, {
                        Timestamps: asked.minutes.map((at) => new Date(at).toISOString().replace('.000Z', '.0001Z')),
                    })
                )),
            /-reader's capacity read has a timestamp that is not a time: /,
        ],
        [
            'a capacity read that is only one page',
            {},
            (run) =>
                (run.aws = answeringCapacity(run.cloud, (asked) => ({
                    ...(idleAnswer(asked) as object),
                    NextToken: 'page-2',
                }))),
            /CloudWatch answered with a NextToken, so the answer is only one page/,
        ],
        [
            'a run manifest without the reader idle limit',
            {},
            (run) => delete run.manifest.readerIdleMaxAcu,
            /names no idle limit for .*-reader, so set readerAcu\.idleMax in the cloud profile/,
        ],
        [
            'a run manifest without the reader minimum',
            {},
            (run) => delete run.manifest.readerMinAcu,
            /names no minimum for .*-reader, so lease the run again/,
        ],
        [
            'a reader with fewer than five capacity minutes',
            { liveReaderAcu: { maxima: [1, 1, 1, 1] } },
            () => undefined,
            /has 4 consecutive complete capacity minutes, under the 5 it needs/,
        ],
        [
            'a reader whose last five capacity points skip a minute',
            { liveReaderAcu: { maxima: [1, 1, 1, null, 1, 1] } },
            () => undefined,
            /has 2 consecutive complete capacity minutes, under the 5 it needs/,
        ],
        [
            'a capacity query that ends before the newest complete minute',
            { now: () => new Date(Date.now() + MINUTE_MS) },
            () => undefined,
            /has 4 consecutive complete capacity minutes, under the 5 it needs/,
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

    const leasedHostRun = async (cloud: FakeCloud, dir: string, idleMax: number): Promise<Run> => {
        const controller = {
            aws: cloud,
            now: () => new Date(),
            print: () => undefined,
            warn: () => undefined,
        } as unknown as Controller
        const profile = CloudProfile.parse({ ...PROFILE, readerAcu: { ...PROFILE.readerAcu, idleMax } })
        const runner = { file: 'runner.yaml', bytes: Buffer.from(''), sha256: '' }
        const { runId } = await lease(
            controller,
            { profile, runner, inputs: [runner], card: { id: 'cyclotron-failover-under-load', failsOver: true } },
            { owner: 'scenario-tests', commit: 'abc123' }
        )
        const file = path.join(dir, `${runId}.json`)
        writeFileSync(file, cloud.objects.get(keyOf(runId, 'input/manifest.json'))!)
        const manifest = runManifestOf({ SCENARIO_RUN_MANIFEST: file })!
        return { cloud, ...cloud.runCluster(runId), manifest }
    }

    const cloudReading = (maxima: number[]): FakeCloud =>
        new FakeCloud({ now: () => new Date(), failover: { takesMs: 20 }, liveReaderAcu: { maxima } })

    it('refuses a reader under the minimum its cloud profile leases into the manifest the host reads', async () => {
        using dir = mkdtempDisposableSync(path.join(tmpdir(), 'failover-manifest-'))
        const cloud = cloudReading([1, 0.5, 1, 1, 1])

        await expect(failOverOn(await leasedHostRun(cloud, dir.path, 2.5))).rejects.toThrow(
            /-reader's capacity read has a value below 1 at /
        )
        expect(cloud.promotions).toEqual([])
    })

    it('refuses a reader above the idle limit its cloud profile leases into the manifest the host reads', async () => {
        using dir = mkdtempDisposableSync(path.join(tmpdir(), 'failover-manifest-'))
        const cloud = cloudReading([2, 2, 2, 2, 2])

        await expect(failOverOn(await leasedHostRun(cloud, dir.path, 1.5))).rejects.toThrow(
            /was above its 1.5 ACU idle limit in its last 5 minutes: 2 at /
        )
        expect(cloud.promotions).toEqual([])
    })

    it('promotes a reader inside the bounds its cloud profile leases into the manifest the host reads', async () => {
        using dir = mkdtempDisposableSync(path.join(tmpdir(), 'failover-manifest-'))
        const cloud = cloudReading([2, 2, 2, 2, 2])
        const run = await leasedHostRun(cloud, dir.path, 2.5)

        const actuation = await failOverOn(run)
        await actuation.release()

        expect(cloud.promotions.map(({ to }) => to)).toEqual([run.reader, run.writer])
    })

    it.each<[string, FakeCloudOptions['liveReaderAcu']]>([
        ['at its minimum', { maxima: [1, 1, 1, 1, 1] }],
        ['idle above its minimum, under the idle limit', { maxima: [2, 2, 2, 2, 2] }],
        ['at the idle limit', { maxima: [2, 2.5, 2, 2, 2] }],
        [
            'idle on average in a minute its maximum bursts above the idle limit',
            { maxima: [1, 1, 5, 1, 1], averages: [1, 1, 1.6, 1, 1] },
        ],
    ])(
        'promotes a reader %s, observes each recovery stage, then fails back to the original writer',
        async (_story, liveReaderAcu) => {
            const run = runOf({ liveReaderAcu })

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
        }
    )

    it('promotes on an idle capacity read in the GetMetricData shape, which comes ascending only when asked', async () => {
        const run = runOf()
        run.aws = answeringCapacity(run.cloud, (asked) => idleAnswer(asked))

        const actuation = await failOverOn(run)
        await actuation.release()

        expect(run.cloud.promotions.map(({ to }) => to)).toEqual([run.reader, run.writer])
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

    it.each<[string, number, (cloud: FakeCloud) => void, number, string | undefined]>([
        [
            'observes a promotion whose response was lost',
            20,
            (cloud) => cloud.loseResponseOf('failover-db-cluster'),
            1,
            undefined,
        ],
        [
            'leaves a lost response that never promotes unobserved',
            Infinity,
            (cloud) => cloud.loseResponseOf('failover-db-cluster'),
            1,
            'failover request ambiguous, not observed: aws rds failover-db-cluster exited 255',
        ],
        [
            'observes a request the service answered with a server fault, rather than calling it refused',
            20,
            (cloud) => cloud.failWhen('failover-db-cluster', () => true),
            0,
            'failover request ambiguous, not observed: aws failover-db-cluster exited 254: An error occurred (InternalFailure)',
        ],
    ])('%s, sending the request once', async (_story, takesMs, arrange, promotions, unobserved) => {
        const run = runOf({ failover: { takesMs } })
        arrange(run.cloud)

        const actuation = await failOverOn(run)

        await expect(actuation.observed()).resolves.toBe(unobserved === undefined)
        expect(run.cloud.promotions).toHaveLength(promotions)
        expect(actuation.journal().unobserved).toEqual(unobserved && expect.stringContaining(unobserved))
    })

    it('counts no recovery stage seen after its deadline', async () => {
        const run = runOf()
        run.cloud.holdPromotions()
        const slowIdentity = async (): Promise<{ instance: string; inRecovery: boolean }> => {
            await sleep(OBSERVE_WITHIN_MS + 100)
            run.cloud.landPromotions()
            return { instance: run.cloud.writerOf(run.cluster)!, inRecovery: false }
        }

        const actuation = await failOverOn(run, { identity: slowIdentity })

        await expect(actuation.observed()).resolves.toBe(false)
        expect(actuation.journal()).toMatchObject({
            observations: [],
            unobserved: expect.stringMatching(/did not show cluster_writer, sql_writer, first_probe_commit/),
        })
    })

    it('counts no recovery stage seen once the hold was cancelled', async () => {
        const run = runOf()
        const hold = new AbortController()
        const cancelledMidRequest = (): Promise<SqlIdentity> => {
            const instance = run.cloud.writerOf(run.cluster)!
            if (instance === run.reader) {
                hold.abort()
            }
            return Promise.resolve({ instance, inRecovery: false })
        }

        const actuation = await failOverOn(run, { identity: cancelledMidRequest })

        await expect(actuation.observed(hold.signal)).resolves.toBe(false)
        expect(actuation.journal().observations!.map(({ name }) => name)).not.toContain('sql_writer')
    })

    it('leaves no read that fails after the hold was cancelled unhandled', async () => {
        const unhandled: unknown[] = []
        const keep = (reason: unknown): number => unhandled.push(reason)
        process.on('unhandledRejection', keep)
        try {
            const run = runOf()
            const hold = new AbortController()
            const actuation = await failOverOn(run, { identity: () => Promise.reject(new Error('connection refused')) })
            run.cloud.beforeCall('describe-db-clusters', () => hold.abort())

            await expect(actuation.observed(hold.signal)).resolves.toBe(false)
            await new Promise((resolve) => setImmediate(resolve))

            expect(unhandled).toEqual([])
        } finally {
            process.off('unhandledRejection', keep)
        }
    })

    it.each<[string, (actuation: FailoverActuation, stall: () => void) => Promise<unknown>, Record<string, unknown>]>([
        [
            'bounds an observation whose cluster read never answers',
            (actuation, stall) => {
                stall()
                return actuation.observed()
            },
            {
                observations: OBSERVED.slice(1),
                unobserved: expect.stringMatching(/did not show cluster_writer within/),
            },
        ],
        [
            'bounds a fail-back whose settle read never answers',
            async (actuation, stall) => {
                await actuation.observed(AbortSignal.abort())
                stall()
                await actuation.release()
            },
            { releaseError: expect.stringMatching(/stayed unanswered for 0\.4s after the hold/) },
        ],
    ])('%s', async (_story, act, journalled) => {
        const run = runOf()
        let stalled = false
        const aws = {
            call: (args: string[]): Promise<unknown> =>
                stalled && args[1] === 'describe-db-clusters' ? new Promise(() => undefined) : run.cloud.call(args),
            text: (args: string[]): Promise<string> => run.cloud.text(args),
        }
        const actuation = await failOverOn(run, { aws })

        await act(actuation, () => (stalled = true))

        expect(actuation.journal()).toMatchObject(journalled)
    })

    it.each<[string, boolean, string, Record<string, unknown>]>([
        [
            'fails back a promotion that lands while the release waits for it to settle',
            true,
            'writer',
            { releaseIntentAt: expect.any(String), releaseObservations: OBSERVED },
        ],
        [
            'records a promotion that never settles instead of leaving the cluster on the reader unremarked',
            false,
            'reader',
            { releaseError: expect.stringMatching(/stayed failing-over for 0\.4s after the hold/) },
        ],
    ])('%s', async (_story, lands, endsOn, journalled) => {
        const run = runOf()
        run.cloud.holdPromotions()
        const actuation = await failOverOn(run)
        await expect(actuation.observed(AbortSignal.abort())).resolves.toBe(false)
        if (lands) {
            let describes = 0
            run.cloud.beforeCall('describe-db-clusters', () => {
                if (describes++ === 1) {
                    run.cloud.landPromotions()
                }
            })
        }

        await actuation.release()

        if (endsOn === 'writer') {
            expect(run.cloud.writerOf(run.cluster)).toBe(run.writer)
        }
        expect(run.cloud.promotions.map(({ to }) => to)).toEqual(
            endsOn === 'writer' ? [run.reader, run.writer] : [run.reader]
        )
        expect(actuation.journal()).toMatchObject(journalled)
    })

    it.each<[string, Partial<FakeCloudOptions>, 'writer' | 'reader', Record<string, unknown>]>([
        [
            'fails back a promotion the cluster shows only after the release began',
            { failover: { takesMs: 100, showsAfterMs: 50 } },
            'writer',
            { releaseIntentAt: expect.any(String), releaseObservations: OBSERVED },
        ],
        [
            'records an accepted promotion the cluster never showed instead of calling the release clean',
            { failover: { takesMs: Infinity, showsAfterMs: Infinity } },
            'reader',
            {
                releaseError: expect.stringMatching(
                    /-reader had not taken over 0\.4s after the hold, so the failover request may still land/
                ),
            },
        ],
    ])('%s', async (_story, options, endsOn, journalled) => {
        const run = runOf(options)
        const actuation = await failOverOn(run)
        await expect(actuation.observed(AbortSignal.abort())).resolves.toBe(false)

        await actuation.release()

        expect(run.cloud.promotions.map(({ to }) => to)).toEqual(
            endsOn === 'writer' ? [run.reader, run.writer] : [run.reader]
        )
        expect(actuation.journal()).toMatchObject(journalled)
    })

    it.each<[string, string, number, (actuation: Promise<FailoverActuation>) => Promise<unknown>]>([
        [
            'refuses a failover whose precondition read never answers once the apply stops',
            'sts',
            60_000,
            (applied) =>
                expect(applied).rejects.toThrow(/^pg\.failover refused: AWS had not answered when the apply stopped/),
        ],
        [
            'leaves a failover request that never answers ambiguous, and records it at release',
            'rds',
            OBSERVE_WITHIN_MS,
            async (applied) => {
                const actuation = await applied
                await expect(actuation.observed()).resolves.toBe(false)
                await actuation.release()
                expect(actuation.journal()).toMatchObject({
                    unobserved: expect.stringMatching(
                        /^failover request ambiguous, not observed: AWS had not answered/
                    ),
                    releaseError: expect.stringMatching(/the failover request may still land/),
                })
            },
        ],
    ])('%s', async (_story, stalls, observeWithinMs, expectApplied) => {
        const run = runOf()
        const stopped = new AbortController()
        const aws = {
            call: (args: string[]): Promise<unknown> =>
                args[0] === stalls && args[1] !== 'describe-db-clusters'
                    ? (stopped.abort(), new Promise(() => undefined))
                    : run.cloud.call(args),
            text: (args: string[]): Promise<string> => run.cloud.text(args),
        }

        await expectApplied(failOverOn(run, { aws, signal: stopped.signal, observeWithinMs }))
    })

    it('observes a promotion and its fail-back while AWS answers neither request, and ends with the hold', async () => {
        const run = runOf()
        const aws = {
            call: (args: string[]): Promise<unknown> => {
                const answer = run.cloud.call(args)
                return args[1] === 'failover-db-cluster' ? new Promise(() => undefined) : answer
            },
            text: (args: string[]): Promise<string> => run.cloud.text(args),
        }
        const hold = new AbortController()
        const actuation = await failOverOn(run, { aws, observeWithinMs: 60_000 })

        const observed = actuation.observed(hold.signal)
        await waitForExpect(() => expect(actuation.journal().observations).toEqual(OBSERVED), 2000, 5)
        hold.abort()

        await expect(observed).resolves.toBe(true)
        await actuation.release()
        expect(run.cloud.writerOf(run.cluster)).toBe(run.writer)
        expect(actuation.journal()).toMatchObject({ releaseObservations: OBSERVED })
        expect(actuation.journal().releaseError).toBeUndefined()
    })

    it('sends no failover request once the apply stopped after its last precondition read', async () => {
        const run = runOf()
        const stopped = new AbortController()
        const aws = {
            call: (args: string[]): Promise<unknown> => {
                const answer = run.cloud.call(args)
                if (args[0] === 'cloudwatch') {
                    void answer.then(() => queueMicrotask(() => stopped.abort()))
                }
                return answer
            },
            text: (args: string[]): Promise<string> => run.cloud.text(args),
        }

        await expect(failOverOn(run, { aws, signal: stopped.signal })).rejects.toThrow(
            /^pg\.failover refused: the apply stopped before the failover request was sent/
        )
        expect(run.cloud.promotions).toEqual([])
    })

    it('counts no probe commit that ended at the intent, as a stale sample on the new writer would', async () => {
        const run = runOf()
        const throughPooler = probeThroughPooler(run)
        const intent: { at?: string } = {}
        const staleAtIntent = (): WriterSample[] => [
            ...(intent.at
                ? [{ at: Date.parse(intent.at), monoMs: 0, ok: true, latencyMs: 0, instance: run.reader }]
                : []),
            ...throughPooler(),
        ]
        const actuation = await failOverOn(run, { commits: staleAtIntent })
        intent.at = actuation.journal().intentAt

        await expect(actuation.observed()).resolves.toBe(true)

        const commit = actuation.journal().observations!.find(({ name }) => name === 'first_probe_commit')!
        expect(Date.parse(commit.at)).toBeGreaterThan(Date.parse(intent.at!))
    })

    it('records a refused fail-back instead of throwing it', async () => {
        const run = runOf()
        const actuation = await failOverOn(run)
        await actuation.observed()
        run.cloud.failWhen('failover-db-cluster', (args) => args.includes(run.writer), 'InvalidDBClusterStateFault')

        await actuation.release()

        expect(run.cloud.writerOf(run.cluster)).toBe(run.reader)
        expect(actuation.journal()).toMatchObject({
            releaseIntentAt: expect.any(String),
            releaseError: expect.stringMatching(/^the fail-back request was refused: .*InvalidDBClusterStateFault/),
        })
    })
})
