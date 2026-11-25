import { SESv2Client, SendEmailCommand } from '@aws-sdk/client-sesv2'
import { randomUUID } from 'crypto'
import { once } from 'events'
import { mkdtempSync, rmSync } from 'fs'
import os from 'os'
import path from 'path'
import { setTimeout as sleep } from 'timers/promises'

import { parseJSON } from '~/common/utils/json-parse'
import { internalFetch } from '~/common/utils/request'
import { waitForExpect } from '~/tests/helpers/expectations'

import { ValveEntry } from '../cards/schema'
import { FakeCloud, FakeCloudOptions } from '../cloud/fake-cloud'
import { pinClockAfterMinuteStart } from '../cloud/fixtures'
import { Actuation, createEnvironment } from '../environment/environment'
import { Role } from '../environment/roles'
import { Queue } from '../probe/cyclotron-probe'
import type { WriterSample } from '../probe/writer-probe'
import { ProviderEdge, TruthPage, startProviderEdge } from '../provider-edge'
import { Truth } from '../provider-edge/truth'
import { ValveContext, createValves } from './valves'

const EMAIL_WORKER = 'cdp-cyclotron-worker-email'
const OUR_TEAM = 7

type Job = { team: number; queue: Queue; status: 'available' | 'running' }

type StackSetup = {
    running?: Role[]
    unkillable?: boolean
    finishesJobsFirst?: boolean
    probeFailure?: string
    probeFailsFor?: number
    runningJobs?: number
    releaseFailure?: string
    applyTakesMs?: number
    observesUntilHoldEnds?: boolean
}

function stackOf({
    running = [EMAIL_WORKER],
    unkillable = false,
    finishesJobsFirst = false,
    probeFailure,
    probeFailsFor = Infinity,
    runningJobs = 0,
    releaseFailure,
    applyTakesMs = 0,
    observesUntilHoldEnds = false,
}: StackSetup = {}) {
    let probeReads = 0
    let nextPid = 1
    const processes = new Map<Role, number>(running.map((role) => [role, nextPid++]))
    const gone: number[] = []
    const frozen = new Set<number>()
    const everFrozen: number[] = []
    let roleSessions = 4
    let droppedSessions = 0
    const goneAfterRelease: number[] = []
    let releaseBegan = false
    const jobs: Job[] = []
    const readers: (() => void)[] = []
    let gate: Promise<void> | undefined

    const context: ValveContext = {
        teams: [OUR_TEAM],
        commits: () => [],
        environment: {
            actuate: (action): Promise<Actuation> => {
                if (finishesJobsFirst) {
                    jobs.splice(0)
                }
                if (action.kind === 'edge.fault' || action.kind === 'rds.failover') {
                    return Promise.reject(new Error(`this stack does not model ${action.kind}`))
                }
                if (action.kind === 'pg.terminate') {
                    const dropped = Math.ceil(action.share * roleSessions)
                    roleSessions -= dropped
                    droppedSessions += dropped
                    return Promise.resolve({
                        observed: () => Promise.resolve(dropped > 0),
                        release: () => Promise.resolve(),
                    })
                }
                const pid = processes.get(action.role)
                if (pid === undefined) {
                    return Promise.resolve({
                        observed: () => Promise.reject(new Error(`${action.role} is not running`)),
                        release: () => Promise.resolve(),
                    })
                }
                if (action.kind === 'freeze') {
                    frozen.add(pid)
                    everFrozen.push(pid)
                    return Promise.resolve({
                        observed: () => Promise.resolve(frozen.has(pid)),
                        release: () => {
                            frozen.delete(pid)
                            return Promise.resolve()
                        },
                    })
                }
                if (!unkillable) {
                    gone.push(pid)
                    if (releaseBegan) {
                        goneAfterRelease.push(pid)
                    }
                    processes.set(action.role, nextPid++)
                }
                return Promise.resolve({
                    observed: () => Promise.resolve(gone.includes(pid)),
                    release: () =>
                        releaseFailure === undefined ? Promise.resolve() : Promise.reject(new Error(releaseFailure)),
                })
            },
        },
        probe: {
            runningJobs: async ({ teams, queues }) => {
                readers.splice(0).forEach((read) => read())
                await gate
                if (probeFailure !== undefined && probeReads++ < probeFailsFor) {
                    throw new Error(probeFailure)
                }
                return jobs.filter(
                    (job) => teams.includes(job.team) && queues.includes(job.queue) && job.status === 'running'
                ).length
            },
        },
    }

    let applyReturnedAt: number | undefined
    if (applyTakesMs > 0 || observesUntilHoldEnds) {
        const { actuate } = context.environment
        context.environment = {
            actuate: async (action) => {
                const actuation = await actuate(action)
                await sleep(applyTakesMs)
                applyReturnedAt = Date.now()
                return {
                    ...actuation,
                    observed: async (signal) => {
                        if (observesUntilHoldEnds) {
                            await once(signal!, 'abort')
                        }
                        return await actuation.observed(signal)
                    },
                }
            },
        }
    }

    const run = (count: number, queue: Queue = 'email'): void => {
        jobs.push(...Array.from({ length: count }, () => ({ team: OUR_TEAM, queue, status: 'running' as const })))
    }
    run(runningJobs)

    return {
        context,
        gone: () => [...gone],
        effects: () => ({ gone: [...gone], frozen: [...frozen], everFrozen: [...everFrozen], droppedSessions }),
        goneAfterRelease: () => [...goneAfterRelease],
        applyReturnedAt: () => applyReturnedAt,
        releasing: (release: () => Promise<void>) => {
            releaseBegan = true
            return release()
        },
        run,
        nextRead: () => new Promise<void>((resolve) => readers.push(resolve)),
        holdReads: () => {
            let open = (): void => undefined
            gate = new Promise((resolve) => (open = resolve))
            return () => open()
        },
    }
}

type Effects = ReturnType<ReturnType<typeof stackOf>['effects']>

const kill = (schedule: Pick<ValveEntry, 'at' | 'when'>, holdFor = '10ms'): ValveEntry => ({
    valve: 'role.kill',
    target: EMAIL_WORKER,
    dose: {},
    for: holdFor,
    ...schedule,
})

const freeze = (schedule: Pick<ValveEntry, 'at' | 'when'>): ValveEntry => ({ ...kill(schedule), valve: 'role.freeze' })

const dropConnections = (schedule: Pick<ValveEntry, 'at' | 'when'>): ValveEntry => ({
    valve: 'pg.drop_connections',
    target: 'postgres',
    dose: { share: 0.5 },
    for: '10ms',
    ...schedule,
})

const throttle = (rate: number, holdFor: string): ValveEntry => ({
    valve: 'ses.throttle',
    target: 'ses',
    dose: { rate },
    at: '0ms',
    for: holdFor,
})

const RUNNING_ON_EMAIL = { name: 'running_on_queue' as const, params: { queue: 'email' as const, atLeast: 2 } }

describe('valves', () => {
    const FAILOVER: ValveEntry = { valve: 'pg.failover', target: 'cyclotron', dose: {}, at: '0ms', for: '10m' }
    const STAGES = [
        { name: 'cluster_writer', at: expect.any(String) },
        { name: 'sql_writer', at: expect.any(String) },
        { name: 'first_probe_commit', at: expect.any(String) },
    ]

    afterEach(() => {
        jest.useRealTimers()
    })

    const runClusterOf = (options: Partial<FakeCloudOptions> = {}, stalls?: string) => {
        pinClockAfterMinuteStart()
        const cloud = new FakeCloud({
            now: () => new Date(),
            failover: { takesMs: 20 },
            liveReaderAcu: { maxima: [1, 1, 1, 1, 1] },
            ...options,
        })
        let stalled: () => void = () => undefined
        const stalledOnce = new Promise<void>((resolve) => (stalled = resolve))
        const aws = {
            call: (args: string[]): Promise<unknown> =>
                args[0] === stalls ? (stalled(), new Promise(() => undefined)) : cloud.call(args),
            text: (args: string[]): Promise<string> => cloud.text(args),
        }
        const run = cloud.runCluster(randomUUID())
        const writerNow = (): string => cloud.writerOf(run.cluster)!
        const samples: WriterSample[] = []
        const commits = (): WriterSample[] => {
            samples.push({ at: Date.now(), monoMs: 0, ok: true, latencyMs: 0, instance: writerNow() })
            return samples
        }
        const environment = createEnvironment({
            aws,
            failover: {
                identity: () => Promise.resolve({ instance: writerNow(), inRecovery: false }),
                pollMs: 5,
                observeWithinMs: 30_000,
            },
        })
        return { cloud, ...run, writerNow, commits, environment, stalledOnce }
    }

    it.each<[string, Partial<FakeCloudOptions>, boolean, Record<string, unknown>]>([
        [
            'fails the run cluster over and back, and journals each recovery stage',
            {},
            true,
            {
                intentAt: expect.any(String),
                appliedAt: expect.any(String),
                observedAt: expect.any(String),
                releasedAt: expect.any(String),
                observations: STAGES,
                releaseIntentAt: expect.any(String),
                releaseObservations: STAGES,
            },
        ],
        [
            'records no intent for a failover its preconditions refused',
            { liveReaderAcu: { maxima: [1, 1, 3, 1, 1] } },
            true,
            { error: expect.stringMatching(/^pg\.failover refused: .* was above its 2.5 ACU idle limit/) },
        ],
        [
            'records no intent for a failover whose capacity read has fewer values than timestamps',
            { shortValuesOf: 'Average' },
            true,
            { error: expect.stringMatching(/^pg\.failover refused: .*'s capacity read has 5 timestamps and 4 values/) },
        ],
        [
            'records no intent for a failover whose capacity read has a value that is not a finite number',
            { liveReaderAcu: { maxima: [1, 1, Number.NaN, 1, 1] } },
            true,
            {
                error: expect.stringMatching(
                    /^pg\.failover refused: .*'s capacity read has a value that is not a finite number at /
                ),
            },
        ],
        [
            'records no intent for a failover whose capacity read has no status',
            { liveReaderAcu: { maxima: [2, 2, 2, 2, 2] }, omitsCapacityStatus: true },
            true,
            {
                error: expect.stringMatching(
                    /^pg\.failover refused: .*'s capacity read came back with no status, not Complete/
                ),
            },
        ],
        ['refuses a failover outside a run host', {}, false, { error: 'pg.failover runs only on a run host' }],
    ])('%s', async (_story, options, onRunHost, recorded) => {
        const valves = createValves({ pollMs: 5 })
        const { context } = stackOf()
        const run = runClusterOf(options)

        await valves.start([FAILOVER], {
            ...context,
            commits: run.commits,
            manifest: onRunHost ? run.manifest : undefined,
            environment: run.environment,
        })
        await waitForExpect(
            () => expect(valves.timeline()[0].observedAt ?? valves.timeline()[0].error).toBeDefined(),
            2000,
            5
        )
        await valves.releaseAll()

        expect(valves.timeline()).toEqual([
            { valve: 'pg.failover', target: 'cyclotron', requestedAt: expect.any(String), ...recorded },
        ])
        expect(run.writerNow()).toBe(run.writer)
    })

    it('stops waiting for a failover precondition that never answers once the valves release', async () => {
        const valves = createValves({ pollMs: 5 })
        const { context } = stackOf()
        const run = runClusterOf({}, 'sts')

        await valves.start([FAILOVER], {
            ...context,
            commits: run.commits,
            manifest: run.manifest,
            environment: run.environment,
        })
        await run.stalledOnce
        await valves.releaseAll()

        expect(valves.timeline()).toEqual([
            {
                valve: 'pg.failover',
                target: 'cyclotron',
                requestedAt: expect.any(String),
                error: expect.stringMatching(/^pg\.failover refused: AWS had not answered when the apply stopped/),
            },
        ])
        expect(run.cloud.promotions).toEqual([])
    })

    it('kills the role an entry names once its offset passes, and records every step', async () => {
        const valves = createValves({ pollMs: 5 })
        const stack = stackOf()

        await valves.start([kill({ at: '20ms' })], stack.context)
        expect(stack.gone()).toEqual([])
        await waitForExpect(() => expect(valves.timeline()[0].releasedAt).toBeDefined(), 2000, 5)
        await valves.releaseAll()

        expect(stack.gone()).toEqual([1])
        expect(valves.timeline()).toEqual([
            {
                valve: 'role.kill',
                target: EMAIL_WORKER,
                requestedAt: expect.any(String),
                intentAt: expect.any(String),
                appliedAt: expect.any(String),
                observedAt: expect.any(String),
                releasedAt: expect.any(String),
            },
        ])
    })

    it('waits until enough jobs of its teams run on the queue before it kills', async () => {
        const valves = createValves({ pollMs: 5 })
        const stack = stackOf()
        stack.run(1)
        stack.run(3, 'hogflow')

        await valves.start([kill({ when: RUNNING_ON_EMAIL })], stack.context)
        await stack.nextRead()
        await stack.nextRead()
        expect(stack.gone()).toEqual([])

        stack.run(1)
        await waitForExpect(() => expect(stack.gone()).toEqual([1]), 2000, 5)
        await valves.releaseAll()

        expect(valves.timeline()[0].observedAt).toEqual(expect.any(String))
    })

    const UNTOUCHED: Effects = { gone: [], frozen: [], everFrozen: [], droppedSessions: 0 }

    it.each<[string, ValveEntry, StackSetup, Partial<Effects>]>([
        ['a kill, which replaces the process', kill({ at: '0ms' }), {}, { gone: [1] }],
        ['a freeze, which resumes the same process on release', freeze({ at: '0ms' }), {}, { everFrozen: [1] }],
        [
            'a connection drop, though the workers finish their jobs on new connections',
            dropConnections({ when: RUNNING_ON_EMAIL }),
            { runningJobs: 2, finishesJobsFirst: true },
            { droppedSessions: 2 },
        ],
    ])('applies and observes %s', async (_story, entry, stackSetup, effects) => {
        const valves = createValves({ pollMs: 5 })
        const stack = stackOf(stackSetup)

        await valves.start([entry], stack.context)
        await waitForExpect(() => expect(valves.timeline()[0].releasedAt).toBeDefined(), 2000, 5)
        await valves.releaseAll()

        expect({ effects: stack.effects(), error: valves.timeline()[0].error }).toEqual({
            effects: { ...UNTOUCHED, ...effects },
            error: undefined,
        })
        expect(valves.timeline()[0].observedAt).toEqual(expect.any(String))
    })

    const NEVER_HELD = 'never applied: running_on_queue email at least 2 did not hold before the drive ended'

    it.each<[string, ValveEntry, StackSetup, boolean, string]>([
        ['a waiting entry whose predicate never held', kill({ when: RUNNING_ON_EMAIL }), {}, false, NEVER_HELD],
        [
            'a waiting entry whose predicate held only once the release had begun',
            kill({ when: RUNNING_ON_EMAIL }),
            {},
            true,
            NEVER_HELD,
        ],
        [
            'a waiting entry whose probe failed',
            kill({ when: RUNNING_ON_EMAIL }),
            { probeFailure: 'connection refused' },
            false,
            `${NEVER_HELD}; the probe last failed: connection refused`,
        ],
        [
            'an entry whose offset the drive did not reach',
            kill({ at: '1m' }),
            {},
            false,
            'never applied: released before its offset',
        ],
    ])('never kills for %s', async (_story, entry, stackSetup, heldAcrossRelease, error) => {
        const valves = createValves({ pollMs: 5 })
        const stack = stackOf(stackSetup)

        await valves.start([entry], stack.context)
        const open = heldAcrossRelease ? stack.holdReads() : () => undefined
        if (entry.when) {
            await stack.nextRead()
        }
        const releasing = valves.releaseAll()
        if (heldAcrossRelease) {
            stack.run(2)
        }
        open()
        await releasing

        expect(stack.gone()).toEqual([])
        expect(valves.timeline()).toEqual([expect.objectContaining({ error })])
    })

    it.each(Array.from({ length: 12 }, (_, microtasks) => [microtasks]))(
        'never kills once the release began, when it begins %i microtasks after the probe is read',
        async (microtasks) => {
            const valves = createValves({ pollMs: 5 })
            const stack = stackOf()
            stack.run(2)
            const releasing = stack.nextRead().then(async () => {
                for (let i = 0; i < microtasks; i++) {
                    await Promise.resolve()
                }
                await stack.releasing(() => valves.releaseAll())
            })

            await valves.start([kill({ when: RUNNING_ON_EMAIL })], stack.context)
            await releasing

            expect(stack.goneAfterRelease()).toEqual([])
        }
    )

    it.each<[string, ValveEntry, StackSetup, string]>([
        ['whose kill did not take', kill({ at: '0ms' }), { unkillable: true }, 'applied but not observed'],
        ['whose role was not running', kill({ at: '0ms' }), { running: [] }, `${EMAIL_WORKER} is not running`],
        [
            'whose kill stranded no job, because the worker finished them first',
            kill({ when: RUNNING_ON_EMAIL }),
            { runningJobs: 2, finishesJobsFirst: true },
            'applied after running_on_queue email at least 2 stopped holding',
        ],
        [
            'whose freeze stranded no job, because the worker finished them first',
            freeze({ when: RUNNING_ON_EMAIL }),
            { runningJobs: 2, finishesJobsFirst: true },
            'applied after running_on_queue email at least 2 stopped holding',
        ],
        [
            'whose kill stranded no job, read by a probe that had failed once before',
            kill({ when: RUNNING_ON_EMAIL }),
            { runningJobs: 2, finishesJobsFirst: true, probeFailure: 'connection refused', probeFailsFor: 1 },
            'applied after running_on_queue email at least 2 stopped holding',
        ],
    ])('records an error for an entry %s, and releases it', async (_story, entry, stackSetup, error) => {
        const valves = createValves({ pollMs: 5 })
        const stack = stackOf(stackSetup)

        await valves.start([entry], stack.context)
        await waitForExpect(() => expect(valves.timeline()[0].error).toBeDefined(), 2000, 5)
        await valves.releaseAll()

        expect(valves.timeline()).toEqual([
            expect.objectContaining({ error, appliedAt: expect.any(String), releasedAt: expect.any(String) }),
        ])
        expect(valves.timeline()[0].observedAt).toBeUndefined()
    })

    describe('on the provider edge', () => {
        let edge: ProviderEdge
        let ses: SESv2Client
        let caDir: string
        let truth: Truth

        beforeAll(() => {
            caDir = mkdtempSync(path.join(os.tmpdir(), 'valves-edge-'))
        })

        afterAll(() => {
            rmSync(caDir, { recursive: true, force: true })
        })

        beforeEach(async () => {
            truth = new Truth()
            edge = await startProviderEdge({
                port: 0,
                caDir,
                feedbackUrl: 'http://127.0.0.1:1/public/m/ses_webhook',
                truth,
            })
            ses = new SESv2Client({
                endpoint: edge.url,
                region: 'us-east-1',
                credentials: { accessKeyId: 'edge', secretAccessKey: 'edge' },
                maxAttempts: 1,
            })
        })

        afterEach(async () => {
            ses.destroy()
            await edge.close()
        })

        const onEdge = (): ValveContext => ({
            ...stackOf().context,
            environment: {
                actuate: (action) =>
                    action.kind === 'edge.fault'
                        ? Promise.resolve(edge.hold(action.rule))
                        : Promise.reject(new Error(`no ${action.kind} here`)),
            },
        })

        const onEdgeHeld = (): { context: ValveContext; held: Promise<void> } => {
            let actuated = (): void => undefined
            const held = new Promise<void>((resolve) => (actuated = resolve))
            const { actuate } = onEdge().environment
            return {
                context: {
                    ...onEdge(),
                    environment: {
                        actuate: async (action) => {
                            const hold = await actuate(action)
                            actuated()
                            return hold
                        },
                    },
                },
                held,
            }
        }

        const send = (abortSignal?: AbortSignal): Promise<string> =>
            ses
                .send(
                    new SendEmailCommand({
                        FromEmailAddress: 'flows@www.example.com',
                        Destination: { ToAddresses: ['run-1-1@www.example.com'] },
                        Content: { Simple: { Subject: { Data: 'Hello' }, Body: { Text: { Data: 'Hello' } } } },
                    }),
                    { abortSignal }
                )
                .then(
                    () => 'sent',
                    (error: Error) => error.name
                )

        it('throttles SES sends until the drive ends, and lifts the throttle on release', async () => {
            const valves = createValves({ pollMs: 5 })

            await valves.start([throttle(1, '1m')], onEdge())
            await waitForExpect(() => expect(valves.timeline()[0].appliedAt).toBeDefined(), 2000, 5)
            const outcomes = [await send(), await send()]
            await waitForExpect(() => expect(valves.timeline()[0].observedAt).toBeDefined(), 2000, 5)
            await valves.releaseAll()

            expect(outcomes).toEqual(['sent', 'TooManyRequestsException'])
            expect(await send()).toBe('sent')
            expect(valves.timeline()[0]).toEqual(expect.objectContaining({ releasedAt: expect.any(String) }))
            expect(valves.timeline()[0].error).toBeUndefined()
        })

        it.each([
            ['rejected', 'MessageRejected'],
            ['bounce', 'sent'],
        ])('answers every SES send with a %s while it holds', async (type, outcome) => {
            const valves = createValves({ pollMs: 5 })

            await valves.start([{ valve: 'ses.reject', target: 'ses', dose: { type }, at: '0ms', for: '1m' }], onEdge())
            await waitForExpect(() => expect(valves.timeline()[0].appliedAt).toBeDefined(), 2000, 5)
            const outcomes = [await send(), await send()]
            const truth = parseJSON(await (await internalFetch(`${edge.url}/_truth`)).text()) as TruthPage
            await valves.releaseAll()

            expect({
                outcomes,
                faults: truth.records.filter(({ kind }) => kind === 'ses.send').map(({ fault }) => fault),
            }).toEqual({
                outcomes: [outcome, outcome],
                faults: ['ses.reject', 'ses.reject'],
            })
        })

        it.each<[boolean, (number | string | undefined)[][]]>([
            [
                true,
                [
                    [200, 'ses.ambiguous'],
                    [200, undefined],
                ],
            ],
            [false, [[200, undefined]]],
        ])(
            'drops the connection of the next SES send with ses.ambiguous accepted %s, recording only what SES took',
            async (accepted, sends) => {
                const valves = createValves({ pollMs: 5 })
                const edgeHeld = onEdgeHeld()

                await valves.start(
                    [{ valve: 'ses.ambiguous', target: 'ses', dose: { accepted, count: 1 }, at: '0ms', for: '1m' }],
                    edgeHeld.context
                )
                await edgeHeld.held
                const outcomes = [await send(), await send()]
                const truth = parseJSON(await (await internalFetch(`${edge.url}/_truth`)).text()) as TruthPage
                await valves.releaseAll()

                expect({
                    outcomes,
                    sends: truth.records.map(({ status, fault }) => [status, fault]),
                    error: valves.timeline()[0].error,
                    observed: valves.timeline()[0].observedAt !== undefined,
                }).toEqual({ outcomes: ['Error', 'sent'], sends, error: undefined, observed: true })
            }
        )

        const killAfterAccept = kill({ when: { name: 'edge_accepted', params: { channel: 'ses' } } })

        const withWorker = (running: boolean) => {
            const worker = new AbortController()
            const sentWhenKilled: number[] = []
            let boundaryHeld = (): void => undefined
            const held = new Promise<void>((resolve) => (boundaryHeld = resolve))
            const context: ValveContext = {
                ...onEdge(),
                environment: {
                    actuate: (action) => {
                        if (action.kind === 'edge.fault') {
                            boundaryHeld()
                            return Promise.resolve(edge.hold(action.rule))
                        }
                        if (action.kind !== 'kill' || action.role !== EMAIL_WORKER || !running) {
                            return Promise.reject(new Error(`${EMAIL_WORKER} is not running`))
                        }
                        sentWhenKilled.push(edge.sent.length)
                        worker.abort()
                        return Promise.resolve({
                            observed: () => Promise.resolve(true),
                            release: () => Promise.resolve(),
                        })
                    },
                },
            }
            return { context, held, worker: worker.signal, sentWhenKilled }
        }

        it.each<[string, boolean, string, number[], string | undefined]>([
            [
                'kills the worker after SES took its send, so the send never hears the answer',
                true,
                'AbortError',
                [1],
                undefined,
            ],
            [
                'answers the held send on release when the kill fails',
                false,
                'sent',
                [],
                `${EMAIL_WORKER} is not running`,
            ],
        ])('edge_accepted on ses %s', async (_story, running, outcome, sentWhenKilled, error) => {
            const valves = createValves({ pollMs: 5 })
            const stack = withWorker(running)

            await valves.start([killAfterAccept], stack.context)
            await stack.held
            const answered = await send(stack.worker)
            await valves.releaseAll()

            expect({
                answered,
                sentWhenKilled: stack.sentWhenKilled,
                error: valves.timeline()[0].error,
                observed: valves.timeline()[0].observedAt !== undefined,
                next: await send(),
            }).toEqual({ answered: outcome, sentWhenKilled, error, observed: running, next: 'sent' })
        })

        it.each<[string, boolean, string]>([
            [
                'SES took no send before the drive ended',
                false,
                'never applied: edge_accepted on ses did not happen before the drive ended',
            ],
            ['SES took its send as the drive ended', true, 'never applied: the drive ended before the valve applied'],
        ])('kills nothing and lifts its boundary when %s', async (_story, endsOnSend, error) => {
            const valves = createValves({ pollMs: 5 })
            const stack = withWorker(true)

            await valves.start([killAfterAccept], stack.context)
            await stack.held
            const append = truth.append.bind(truth)
            truth.append = (record) => {
                const appended = append(record)
                void valves.releaseAll()
                return appended
            }
            const heldSend = endsOnSend ? send(stack.worker) : Promise.resolve(undefined)
            if (endsOnSend) {
                await waitForExpect(() => expect(edge.sent).toHaveLength(1), 2000, 5)
            }
            await valves.releaseAll()

            expect({
                error: valves.timeline()[0].error,
                heldSend: await heldSend,
                next: await send(),
                sentWhenKilled: stack.sentWhenKilled,
            }).toEqual({
                error,
                heldSend: endsOnSend ? 'sent' : undefined,
                next: 'sent',
                sentWhenKilled: [],
            })
        })

        it.each<[string, string, boolean]>([
            ['its hold ends', '100ms', true],
            ['the drive ends', '1m', false],
        ])(
            'records a throttle that no send went over as never observed once %s, and lifts it',
            async (_story, holdFor, releasedBeforeDriveEnds) => {
                const valves = createValves({ pollMs: 5 })

                await valves.start([throttle(1, holdFor)], onEdge())
                await waitForExpect(() => expect(valves.timeline()[0].appliedAt).toBeDefined(), 2000, 5)
                expect(await send()).toBe('sent')
                if (releasedBeforeDriveEnds) {
                    await waitForExpect(() => expect(valves.timeline()[0].releasedAt).toBeDefined(), 2000, 5)
                }
                await valves.releaseAll()

                expect(await send()).toBe('sent')
                expect(valves.timeline()[0]).toEqual(
                    expect.objectContaining({
                        error: 'applied but not observed',
                        appliedAt: expect.any(String),
                        releasedAt: expect.any(String),
                    })
                )
                expect(valves.timeline()[0].observedAt).toBeUndefined()
            }
        )
    })

    it('keeps both reasons when a fault it never observed fails to release', async () => {
        const valves = createValves({ pollMs: 5 })
        const stack = stackOf({ unkillable: true, releaseFailure: 'connection refused' })

        await valves.start([kill({ at: '0ms' })], stack.context)
        await waitForExpect(() => expect(valves.timeline()[0].error).toBeDefined(), 2000, 5)
        await valves.releaseAll()

        const { error, releasedAt, observedAt } = valves.timeline()[0]
        expect({ error, releasedAt, observedAt }).toEqual({
            error: 'applied but not observed; connection refused',
            releasedAt: undefined,
            observedAt: undefined,
        })
    })

    it('records a release that failed, and still ends the drive', async () => {
        const valves = createValves({ pollMs: 5 })
        const stack = stackOf({ releaseFailure: 'connection refused' })

        await valves.start([kill({ at: '0ms' })], stack.context)
        await waitForExpect(() => expect(valves.timeline()[0].error).toBeDefined(), 2000, 5)
        await valves.releaseAll()

        expect(valves.timeline()[0]).toEqual(
            expect.objectContaining({ observedAt: expect.any(String), error: 'connection refused' })
        )
        expect(valves.timeline()[0].releasedAt).toBeUndefined()
    })

    it('cuts an applied entry short when the drive ends before its hold does', async () => {
        const valves = createValves({ pollMs: 5 })
        const stack = stackOf()

        await valves.start([kill({ at: '0ms' }, '1m')], stack.context)
        await waitForExpect(() => expect(valves.timeline()[0].observedAt).toBeDefined(), 2000, 5)
        await Promise.all([valves.releaseAll(), valves.releaseAll()])

        expect(stack.gone()).toEqual([1])
        expect(valves.timeline()[0].releasedAt).toEqual(expect.any(String))
    })

    it.each<[string, StackSetup]>([
        ['a slow apply returns', { applyTakesMs: 100 }],
        ['observing lasts until the hold ends', { applyTakesMs: 100, observesUntilHoldEnds: true }],
    ])('records the intent before apply and holds from the moment apply returns, when %s', async (_story, setup) => {
        const valves = createValves({ pollMs: 5 })
        const stack = stackOf(setup)

        await valves.start([kill({ at: '0ms' }, '200ms')], stack.context)
        await waitForExpect(() => expect(valves.timeline()[0].releasedAt).toBeDefined(), 2000, 5)
        await valves.releaseAll()

        const { intentAt, appliedAt, observedAt, releasedAt, error } = valves.timeline()[0]
        const applyReturnedAt = stack.applyReturnedAt()
        expect({ observedAt, error }).toEqual({ observedAt: expect.any(String), error: undefined })
        expect(applyReturnedAt! - Date.parse(intentAt!)).toBeGreaterThanOrEqual(95)
        expect(Date.parse(appliedAt!)).toBeGreaterThanOrEqual(applyReturnedAt!)
        expect(Date.parse(releasedAt!) - applyReturnedAt!).toBeGreaterThanOrEqual(195)
    })
})
