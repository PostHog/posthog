import { SESv2Client, SendEmailCommand } from '@aws-sdk/client-sesv2'
import { mkdtempSync, rmSync } from 'fs'
import http from 'http'
import { AddressInfo } from 'net'
import os from 'os'
import path from 'path'

import { parseJSON } from '~/common/utils/json-parse'
import { internalFetch } from '~/common/utils/request'
import { waitForExpect } from '~/tests/helpers/expectations'

import { ValveEntry } from '../cards/schema'
import { Actuation } from '../environment/environment'
import { Role } from '../environment/roles'
import { Queue } from '../probe/cyclotron-probe'
import { ProviderEdge, TruthPage, startProviderEdge } from '../provider-edge'
import { ValveContext, createValves } from './valves'

const EMAIL_WORKER = 'cdp-cyclotron-worker-email'
const OUR_TEAM = 7

type Job = { team: number; queue: Queue; status: 'available' | 'running' }

type StackSetup = {
    running?: Role[]
    unkillable?: boolean
    finishesJobsBeforeKill?: boolean
    probeFailure?: string
    probeFailsFor?: number
    runningJobs?: number
    releaseFailure?: string
}

function stackOf({
    running = [EMAIL_WORKER],
    unkillable = false,
    finishesJobsBeforeKill = false,
    probeFailure,
    probeFailsFor = Infinity,
    runningJobs = 0,
    releaseFailure,
}: StackSetup = {}) {
    let probeReads = 0
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
        edgeUrl: 'http://127.0.0.1:1',
        environment: {
            actuate: (action): Promise<Actuation> => {
                const pid = processes.get(action.role)
                if (pid === undefined) {
                    return Promise.resolve({
                        observed: () => Promise.reject(new Error(`${action.role} is not running`)),
                        release: () => Promise.resolve(),
                    })
                }
                if (finishesJobsBeforeKill) {
                    jobs.splice(0)
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

    const run = (count: number, queue: Queue = 'email'): void => {
        jobs.push(...Array.from({ length: count }, () => ({ team: OUR_TEAM, queue, status: 'running' as const })))
    }
    run(runningJobs)

    return {
        context,
        gone: () => [...gone],
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

const kill = (schedule: Pick<ValveEntry, 'at' | 'when'>, holdFor = '10ms'): ValveEntry => ({
    valve: 'role.kill',
    target: EMAIL_WORKER,
    dose: {},
    for: holdFor,
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
            { runningJobs: 2, finishesJobsBeforeKill: true },
            'applied after running_on_queue email at least 2 stopped holding',
        ],
        [
            'whose kill stranded no job, read by a probe that had failed once before',
            kill({ when: RUNNING_ON_EMAIL }),
            { runningJobs: 2, finishesJobsBeforeKill: true, probeFailure: 'connection refused', probeFailsFor: 1 },
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

        beforeAll(() => {
            caDir = mkdtempSync(path.join(os.tmpdir(), 'valves-edge-'))
        })

        afterAll(() => {
            rmSync(caDir, { recursive: true, force: true })
        })

        beforeEach(async () => {
            edge = await startProviderEdge({
                port: 0,
                caDir,
                feedbackUrl: 'http://127.0.0.1:1/public/m/ses_webhook',
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

        const send = (): Promise<string> =>
            ses
                .send(
                    new SendEmailCommand({
                        FromEmailAddress: 'flows@www.example.com',
                        Destination: { ToAddresses: ['run-1-1@www.example.com'] },
                        Content: { Simple: { Subject: { Data: 'Hello' }, Body: { Text: { Data: 'Hello' } } } },
                    })
                )
                .then(
                    () => 'sent',
                    (error: Error) => error.name
                )

        it('throttles SES sends until the drive ends, and lifts the throttle on release', async () => {
            const valves = createValves({ pollMs: 5 })

            await valves.start([throttle(1, '1m')], { ...stackOf().context, edgeUrl: edge.url })
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

            await valves.start([{ valve: 'ses.reject', target: 'ses', dose: { type }, at: '0ms', for: '1m' }], {
                ...stackOf().context,
                edgeUrl: edge.url,
            })
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

        it.each<[string, string, number | undefined, 'error' | 'releasedAt' | undefined]>([
            ['its observation window passes', '1m', 50, 'error'],
            ['its hold ends', '100ms', undefined, 'releasedAt'],
            ['the drive ends', '1m', undefined, undefined],
        ])(
            'records a throttle that no send went over as never observed once %s, and lifts it',
            async (_story, holdFor, faultObservedWithinMs, recordedBeforeDriveEnds) => {
                const valves = createValves({ pollMs: 5, faultObservedWithinMs })

                await valves.start([throttle(1, holdFor)], { ...stackOf().context, edgeUrl: edge.url })
                await waitForExpect(() => expect(valves.timeline()[0].appliedAt).toBeDefined(), 2000, 5)
                expect(await send()).toBe('sent')
                if (recordedBeforeDriveEnds) {
                    await waitForExpect(
                        () => expect(valves.timeline()[0][recordedBeforeDriveEnds]).toBeDefined(),
                        2000,
                        5
                    )
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

    async function fakeEdge({
        observation,
        removed,
    }: {
        observation: 'held' | 'none applied' | 'applied after 100ms'
        removed: number
    }) {
        const requests: string[] = []
        let observationAsked!: () => void
        const asked = new Promise<void>((resolve) => (observationAsked = resolve))
        const server = http.createServer((req, res) => {
            requests.push(`${req.method} ${req.url}`)
            if (req.method === 'POST') {
                res.writeHead(201).end(JSON.stringify({ id: 'fault-1' }))
            } else if (req.method === 'DELETE') {
                res.writeHead(removed).end()
            } else if (observation === 'held') {
                observationAsked()
            } else if (observation === 'applied after 100ms') {
                setTimeout(() => res.writeHead(200).end(JSON.stringify({ applied: 1 })), 100)
            } else {
                res.writeHead(200).end(JSON.stringify({ applied: 0 }))
            }
        })
        await new Promise<void>((resolve) => server.listen(0, '127.0.0.1', resolve))
        return {
            edgeUrl: `http://127.0.0.1:${(server.address() as AddressInfo).port}`,
            asked,
            removals: () => requests.filter((request) => request.startsWith('DELETE')),
            close: async () => {
                server.closeAllConnections()
                await new Promise((closed) => server.close(closed))
            },
        }
    }

    it('ends the drive while an observation request is still open, and lifts the fault', async () => {
        const edge = await fakeEdge({ observation: 'held', removed: 204 })
        const valves = createValves({ pollMs: 5 })
        try {
            await valves.start([throttle(1, '60m')], { ...stackOf().context, edgeUrl: edge.edgeUrl })
            await edge.asked
            await valves.releaseAll()

            const { error, releasedAt, observedAt } = valves.timeline()[0]
            expect({ error, releasedAt, observedAt, removals: edge.removals() }).toEqual({
                error: 'applied but not observed',
                releasedAt: expect.any(String),
                observedAt: undefined,
                removals: ['DELETE /_faults/fault-1'],
            })
        } finally {
            await edge.close()
        }
    })

    it('does not observe a fault from a hit the edge reports after the observation window', async () => {
        const edge = await fakeEdge({ observation: 'applied after 100ms', removed: 204 })
        const valves = createValves({ pollMs: 5, faultObservedWithinMs: 20 })
        try {
            await valves.start([throttle(1, '60m')], { ...stackOf().context, edgeUrl: edge.edgeUrl })
            await waitForExpect(() => expect(valves.timeline()[0].error).toBeDefined(), 2000, 5)
            await valves.releaseAll()

            const { error, observedAt } = valves.timeline()[0]
            expect({ error, observedAt }).toEqual({ error: 'applied but not observed', observedAt: undefined })
        } finally {
            await edge.close()
        }
    })

    it('keeps both reasons when the edge refuses to remove a fault it never observed', async () => {
        const edge = await fakeEdge({ observation: 'none applied', removed: 500 })
        const valves = createValves({ pollMs: 5, faultObservedWithinMs: 20 })
        try {
            await valves.start([throttle(1, '60m')], { ...stackOf().context, edgeUrl: edge.edgeUrl })
            await waitForExpect(() => expect(valves.timeline()[0].error).toBeDefined(), 2000, 5)
            await valves.releaseAll()

            const { error, releasedAt, observedAt } = valves.timeline()[0]
            expect({ error, releasedAt, observedAt, removals: edge.removals() }).toEqual({
                error: 'applied but not observed; The edge did not remove the ses.throttle fault: it answered 500',
                releasedAt: undefined,
                observedAt: undefined,
                removals: ['DELETE /_faults/fault-1'],
            })
        } finally {
            await edge.close()
        }
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
})
