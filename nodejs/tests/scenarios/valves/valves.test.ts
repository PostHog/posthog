import { waitForExpect } from '~/tests/helpers/expectations'

import { ValveEntry } from '../cards/schema'
import { Action, Actuation } from '../environment/environment'
import { ValveContext, createValves } from './valves'

const EMAIL_WORKER = 'cdp-cyclotron-worker-email'

type Recorded = { actions: Action[]; released: number; polls: number }

function contextOf(observe: () => Promise<boolean>, running: () => number): ValveContext & { recorded: Recorded } {
    const recorded: Recorded = { actions: [], released: 0, polls: 0 }
    return {
        recorded,
        teams: [7],
        environment: {
            actuate: (action): Promise<Actuation> => {
                recorded.actions.push(action)
                return Promise.resolve({
                    observed: observe,
                    release: () => {
                        recorded.released += 1
                        return Promise.resolve()
                    },
                })
            },
        },
        probe: {
            runningJobs: ({ teams, queues }) => {
                recorded.polls += 1
                expect({ teams, queues }).toEqual({ teams: [7], queues: ['email'] })
                return Promise.resolve(running())
            },
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

const OBSERVED = (): Promise<boolean> => Promise.resolve(true)

describe('valves', () => {
    it('kills the role an entry names once its offset passes, and records every step', async () => {
        const valves = createValves({ pollMs: 5 })
        const context = contextOf(OBSERVED, () => 0)

        await valves.start([kill({ at: '20ms' })], context)
        expect(context.recorded.actions).toEqual([])
        await waitForExpect(() => expect(valves.timeline()[0].releasedAt).toBeDefined(), 2000, 5)
        await valves.releaseAll()

        expect(context.recorded).toMatchObject({ actions: [{ kind: 'kill', role: EMAIL_WORKER }], released: 1 })
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

    it('waits for the queue to run enough jobs, polling the probe, before it acts', async () => {
        const valves = createValves({ pollMs: 5 })
        let running = 0
        const context = contextOf(OBSERVED, () => running)

        await valves.start([kill({ when: RUNNING_ON_EMAIL })], context)
        await waitForExpect(() => expect(context.recorded.polls).toBeGreaterThan(2), 2000, 5)
        expect(context.recorded.actions).toEqual([])

        running = 2
        await waitForExpect(() => expect(context.recorded.actions).toHaveLength(1), 2000, 5)
        await valves.releaseAll()

        expect(context.recorded.actions).toEqual([{ kind: 'kill', role: EMAIL_WORKER }])
        expect(valves.timeline()[0].observedAt).toEqual(expect.any(String))
    })

    it.each<[string, ValveEntry, () => Promise<boolean>, string]>([
        [
            'whose predicate never held before release',
            kill({ when: RUNNING_ON_EMAIL }),
            OBSERVED,
            'never applied: running_on_queue email at least 2 did not hold before the drive ended',
        ],
        [
            'that was applied but never observed',
            kill({ at: '0ms' }),
            () => Promise.resolve(false),
            'applied but not observed',
        ],
        [
            'whose actuation failed',
            kill({ at: '0ms' }),
            () => Promise.reject(new Error('no such process group')),
            'no such process group',
        ],
    ])('records an error for an entry %s', async (_story, entry, observe, error) => {
        const valves = createValves({ pollMs: 5 })
        const context = contextOf(observe, () => 0)

        await valves.start([entry], context)
        await waitForExpect(
            () => expect(context.recorded.polls + context.recorded.actions.length).toBeGreaterThan(0),
            2000,
            5
        )
        await valves.releaseAll()

        expect(valves.timeline()).toEqual([expect.objectContaining({ error })])
        expect(valves.timeline()[0].observedAt).toBeUndefined()
    })

    it('cuts an applied entry short when released before its hold ends, releasing it once', async () => {
        const valves = createValves({ pollMs: 5 })
        const context = contextOf(OBSERVED, () => 0)

        await valves.start([kill({ at: '0ms' }, '1m')], context)
        await waitForExpect(() => expect(valves.timeline()[0].observedAt).toBeDefined(), 2000, 5)
        await Promise.all([valves.releaseAll(), valves.releaseAll()])
        await valves.releaseAll()

        expect(context.recorded.released).toBe(1)
        expect(valves.timeline()[0].releasedAt).toEqual(expect.any(String))
    })
})
