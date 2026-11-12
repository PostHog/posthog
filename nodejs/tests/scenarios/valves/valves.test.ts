import { setTimeout as sleep } from 'timers/promises'

import { waitForExpect } from '~/tests/helpers/expectations'

import { ValveEntry } from '../cards/schema'
import { Actuation } from '../environment/environment'
import { Role } from '../environment/roles'
import { Queue } from '../probe/cyclotron-probe'
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
    applyTakesMs?: number
    observeTakesMs?: number
}

function stackOf({
    running = [EMAIL_WORKER],
    unkillable = false,
    finishesJobsFirst = false,
    probeFailure,
    probeFailsFor = Infinity,
    runningJobs = 0,
    applyTakesMs = 0,
    observeTakesMs = 0,
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
        environment: {
            actuate: (action): Promise<Actuation> => {
                if (finishesJobsFirst) {
                    jobs.splice(0)
                }
                if (action.kind === 'edge.fault') {
                    return Promise.reject(new Error('this stack has no provider edge'))
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
                    release: () => Promise.resolve(),
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

    if (applyTakesMs > 0 || observeTakesMs > 0) {
        const { actuate } = context.environment
        context.environment = {
            actuate: async (action) => {
                const actuation = await actuate(action)
                await sleep(applyTakesMs)
                return {
                    ...actuation,
                    observed: (signal) => sleep(observeTakesMs).then(() => actuation.observed(signal)),
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

const RUNNING_ON_EMAIL = { name: 'running_on_queue' as const, params: { queue: 'email' as const, atLeast: 2 } }

describe('valves', () => {
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

    it('cuts an applied entry short when the drive ends before its hold does', async () => {
        const valves = createValves({ pollMs: 5 })
        const stack = stackOf()

        await valves.start([kill({ at: '0ms' }, '1m')], stack.context)
        await waitForExpect(() => expect(valves.timeline()[0].observedAt).toBeDefined(), 2000, 5)
        await Promise.all([valves.releaseAll(), valves.releaseAll()])

        expect(stack.gone()).toEqual([1])
        expect(valves.timeline()[0].releasedAt).toEqual(expect.any(String))
    })

    it.each<[string, StackSetup, string, number, number]>([
        ['a slow apply returns', { applyTakesMs: 300 }, '50ms', 45, 250],
        ['observing took most of it', { observeTakesMs: 400 }, '500ms', 450, 800],
    ])('holds an entry for its duration from apply after %s', async (_story, setup, holdFor, atLeast, below) => {
        const valves = createValves({ pollMs: 5 })
        const stack = stackOf(setup)

        await valves.start([kill({ at: '0ms' }, holdFor)], stack.context)
        await waitForExpect(() => expect(valves.timeline()[0].releasedAt).toBeDefined(), 2000, 5)
        await valves.releaseAll()

        const { appliedAt, observedAt, releasedAt, error } = valves.timeline()[0]
        const heldMs = Date.parse(releasedAt!) - Date.parse(appliedAt!)
        expect({ observedAt, error }).toEqual({ observedAt: expect.any(String), error: undefined })
        expect(heldMs).toBeGreaterThanOrEqual(atLeast)
        expect(heldMs).toBeLessThan(below)
    })
})
