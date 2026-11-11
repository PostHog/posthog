import { waitForExpect } from '~/tests/helpers/expectations'

import { ValveEntry } from '../cards/schema'
import { Actuation } from '../environment/environment'
import { Role } from '../environment/roles'
import { Queue } from '../probe/cyclotron-probe'
import { ValveContext, createValves } from './valves'

const EMAIL_WORKER = 'cdp-cyclotron-worker-email'
const OUR_TEAM = 7

type Job = { team: number; queue: Queue; status: 'available' | 'running' }

function stackOf({ running = [EMAIL_WORKER], unkillable = false }: { running?: Role[]; unkillable?: boolean } = {}) {
    let nextPid = 1
    const processes = new Map<Role, number>(running.map((role) => [role, nextPid++]))
    const gone: number[] = []
    const goneAfterRelease: number[] = []
    let releaseBegan = false
    const jobs: Job[] = []
    const readers: (() => void)[] = []
    let gate: Promise<void> | undefined

    const context: ValveContext = {
        teams: [OUR_TEAM],
        environment: {
            actuate: (action): Promise<Actuation> => {
                const pid = processes.get(action.role)
                if (pid === undefined) {
                    return Promise.reject(new Error(`${action.role} is not running`))
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
                return jobs.filter(
                    (job) => teams.includes(job.team) && queues.includes(job.queue) && job.status === 'running'
                ).length
            },
        },
    }

    return {
        context,
        gone: () => [...gone],
        goneAfterRelease: () => [...goneAfterRelease],
        releasing: (release: () => Promise<void>) => {
            releaseBegan = true
            return release()
        },
        run: (count: number, queue: Queue = 'email') =>
            jobs.push(...Array.from({ length: count }, () => ({ team: OUR_TEAM, queue, status: 'running' as const }))),
        nextRead: () => new Promise<void>((resolve) => readers.push(resolve)),
        holdReads: () => {
            let open = (): void => undefined
            gate = new Promise((resolve) => (open = resolve))
            return () => open()
        },
    }
}

const kill = (schedule: Pick<ValveEntry, 'at' | 'when'>, holdFor = '10ms'): ValveEntry => ({
    valve: 'role.kill',
    target: EMAIL_WORKER,
    dose: {},
    for: holdFor,
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

    const NEVER_HELD = 'never applied: running_on_queue email at least 2 did not hold before the drive ended'

    it.each<[string, ValveEntry, boolean, string]>([
        ['a waiting entry whose predicate never held', kill({ when: RUNNING_ON_EMAIL }), false, NEVER_HELD],
        [
            'a waiting entry whose predicate held only once the release had begun',
            kill({ when: RUNNING_ON_EMAIL }),
            true,
            NEVER_HELD,
        ],
        [
            'an entry whose offset the drive did not reach',
            kill({ at: '1m' }),
            false,
            'never applied: released before its offset',
        ],
    ])('never kills for %s', async (_story, entry, heldAcrossRelease, error) => {
        const valves = createValves({ pollMs: 5 })
        const stack = stackOf()

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

    it.each<[string, Parameters<typeof stackOf>[0], string]>([
        ['whose kill did not take', { unkillable: true }, 'applied but not observed'],
        ['whose role was not running', { running: [] }, `${EMAIL_WORKER} is not running`],
    ])('records an error for an entry %s', async (_story, stackSetup, error) => {
        const valves = createValves({ pollMs: 5 })
        const stack = stackOf(stackSetup)

        await valves.start([kill({ at: '0ms' })], stack.context)
        await waitForExpect(() => expect(valves.timeline()[0].error).toBeDefined(), 2000, 5)
        await valves.releaseAll()

        expect(valves.timeline()).toEqual([expect.objectContaining({ error, appliedAt: expect.any(String) })])
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
})
