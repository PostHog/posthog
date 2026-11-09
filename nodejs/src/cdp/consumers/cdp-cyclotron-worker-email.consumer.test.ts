import { createMockJobQueue } from '~/tests/helpers/mocks/job-queue.mock'

import { DateTime } from 'luxon'
import { register } from 'prom-client'

import { HogFlow } from '~/cdp/schema/hogflow'
import { closeHub, createHub } from '~/common/utils/db/hub'
import { parseJSON } from '~/common/utils/json-parse'
import { UUIDT } from '~/common/utils/utils'
import { createCdpConsumerDeps } from '~/tests/helpers/cdp'
import { waitForExpect } from '~/tests/helpers/expectations'
import { createTestTeamFixture } from '~/tests/helpers/sql'

import { Hub } from '../../types'
import { FixtureHogFlowBuilder } from '../_tests/builders/hogflow.builder'
import { createHogFlowInvocationContext, insertHogFlow } from '../_tests/fixtures-hogflows'
import { CyclotronV2DequeuedJob } from '../services/cyclotron-v2'
import { TRANSACTIONAL_EMAIL_EVENT } from '../services/hogflows/hogflow-sensitivity'
import { CONSUMER_STOP_DEADLINE_MS, v2JobToInvocation } from '../services/job-queue/job-queue-postgres-v2'
import { LONGEST_WAIT_FOR_ROOM_MS } from '../services/messaging/attachment-horizon'
import { settleBeforeAbortEvenWhileCredentialsStall } from '../services/messaging/attachment-store'
import { ATTACHMENT_SEND_DEADLINE_MS } from '../services/messaging/email.service'
import {
    InFlightLimits,
    InFlightRegistry,
    LARGEST_SEND_FILE_BYTES,
    estimateSend,
} from '../services/messaging/in-flight-registry'
import { CyclotronJobInvocation, CyclotronJobInvocationResult } from '../types'
import { createInvocationResult } from '../utils/invocation-utils'
import { CdpCyclotronWorkerEmail, RESULT_WRITE_MARGIN_MS } from './cdp-cyclotron-worker-email.consumer'

jest.setTimeout(5000)

describe('CdpCyclotronWorkerEmail', () => {
    let hub: Hub

    beforeAll(async () => {
        hub = await createHub()
    })

    afterAll(async () => {
        await closeHub(hub)
    })

    it('should set queue to email', () => {
        const worker = new CdpCyclotronWorkerEmail(hub, createCdpConsumerDeps(hub), createMockJobQueue())
        expect(worker['queue']).toBe('email')
    })

    it('should extend CdpCyclotronWorkerHogFlow', () => {
        const worker = new CdpCyclotronWorkerEmail(hub, createCdpConsumerDeps(hub), createMockJobQueue())
        expect(worker['name']).toBe('CdpCyclotronWorkerEmail')
    })

    it.each([
        ['counts a job the transactional email API marked once, not again on its reschedule', true, [1, 0]],
        ['does not count a job without the mark', false, [0, 0]],
    ])('%s', async (_desc, marked, expectedTriggeredPerRun) => {
        const { team } = await createTestTeamFixture(hub.postgres)
        // The delay parks the run, so the second dequeue is a reschedule of the same job.
        const hogFlow: HogFlow = await insertHogFlow(
            hub.postgres,
            new FixtureHogFlowBuilder()
                .withTeamId(team.id)
                .withStatus('active')
                .withWorkflow({
                    actions: {
                        trigger: { type: 'trigger', config: { type: 'api' } },
                        delay: { type: 'delay', config: { delay_duration: '1h' } },
                        exit: { type: 'exit', config: {} },
                    },
                    edges: [
                        { from: 'trigger', to: 'delay', type: 'continue' },
                        { from: 'delay', to: 'exit', type: 'continue' },
                    ],
                } as any)
                .build()
        )
        const worker = new CdpCyclotronWorkerEmail(hub, createCdpConsumerDeps(hub), createMockJobQueue())
        const triggered = (result: CyclotronJobInvocationResult) =>
            result.metrics.filter((metric) => metric.metric_name === 'triggered')

        let job: CyclotronJobInvocation = {
            id: new UUIDT().toString(),
            teamId: team.id,
            functionId: hogFlow.id,
            queue: 'email',
            queuePriority: 0,
            state: createHogFlowInvocationContext({
                event: { distinct_id: 'distinct_A_1', properties: { to: 'user@example.com' } } as any,
                ...(marked ? { triggerMetricPending: true } : {}),
            }),
        }
        const triggeredPerRun: CyclotronJobInvocationResult['metrics'][] = []
        for (let run = 0; run < 2; run++) {
            const [result] = await worker.processInvocations([job])
            expect(result.finished).toBe(false)
            triggeredPerRun.push(triggered(result))
            // The job queue persists the result's state as JSON, and the next dequeue reads it back.
            job = { ...job, state: parseJSON(JSON.stringify(result.invocation.state)) }
        }

        expect(triggeredPerRun.map((metrics) => metrics.length)).toEqual(expectedTriggeredPerRun)
        expect(triggeredPerRun.flat()).toEqual(
            marked
                ? [
                      {
                          team_id: team.id,
                          app_source_id: hogFlow.id,
                          metric_kind: 'other',
                          metric_name: 'triggered',
                          count: 1,
                      },
                  ]
                : []
        )
    })

    describe('sends with files', () => {
        const FILE_BYTES = 1024 * 1024

        const job = (overrides: Partial<CyclotronJobInvocation> = {}): CyclotronJobInvocation => ({
            id: new UUIDT().toString(),
            teamId: 1,
            functionId: new UUIDT().toString(),
            queue: 'email',
            queuePriority: 0,
            state: createHogFlowInvocationContext(),
            ...overrides,
        })

        const withFiles = (overrides: Partial<CyclotronJobInvocation> = {}): CyclotronJobInvocation =>
            job({
                state: {
                    ...createHogFlowInvocationContext(),
                    send: {
                        attachments: [{ filename: 'invoice.pdf', sha256: 'a'.repeat(64), sizeBytes: FILE_BYTES }],
                    },
                } as any,
                ...overrides,
            })

        const roomFor = (sends: number): InFlightLimits => ({
            budgetBytes: sends * estimateSend(FILE_BYTES).reservedBytes,
            heapLimitBytes: 64 * 1024 * 1024 * 1024,
            maxInFlight: 100,
        })

        const workerWith = (limits: InFlightLimits | null, config: Partial<Hub> = {}) => {
            const queue = createMockJobQueue()
            const worker = new CdpCyclotronWorkerEmail(
                { ...hub, ...config },
                createCdpConsumerDeps(hub),
                queue,
                new InFlightRegistry(limits, () => 0)
            )
            return { worker, queue }
        }

        const resultsOf = (invocations: CyclotronJobInvocation[]): CyclotronJobInvocationResult[] =>
            invocations.map((invocation) => createInvocationResult(invocation))

        const written = (queue: ReturnType<typeof createMockJobQueue>): string[] =>
            queue.queueInvocationResults.mock.calls.flatMap(([results]) => results.map((r) => r.invocation.id))

        it('writes the plain sends of a batch and returns for the next dequeue while a send with files still runs', async () => {
            const { worker, queue } = workerWith(roomFor(1))
            const [plain, slow] = [job(), withFiles()]
            let finishSlow!: () => void
            jest.spyOn(worker, 'processInvocations').mockImplementation((invocations) =>
                invocations[0].id === slow.id
                    ? new Promise((resolve) => (finishSlow = () => resolve(resultsOf(invocations))))
                    : Promise.resolve(resultsOf(invocations))
            )

            const { backgroundTask } = await worker.processBatch([plain, slow])
            let backgroundSettled = false
            void backgroundTask.finally(() => (backgroundSettled = true))
            await waitForExpect(() => expect(written(queue)).toEqual([plain.id]))
            expect(backgroundSettled).toBe(false)

            finishSlow()
            await backgroundTask
            expect(written(queue)).toEqual([plain.id, slow.id])
        })

        it('defers the sends it has no room for, with one more deferral, a longer delay and the first due time', async () => {
            const { worker, queue } = workerWith({ ...roomFor(5), maxInFlight: 1 })
            const firstDueAt = Date.now() - 60_000
            const [admitted, deferred, deferredFirst] = [
                withFiles({ queueMetadata: { attachmentDeferrals: 1, attachmentDueAt: firstDueAt } }),
                withFiles({ queueMetadata: { attachmentDeferrals: 2, attachmentDueAt: firstDueAt } }),
                withFiles({ queueScheduledAt: DateTime.fromMillis(firstDueAt) }),
            ]
            const ran = jest
                .spyOn(worker, 'processInvocations')
                .mockImplementation((invocations) => Promise.resolve(resultsOf(invocations)))
            const before = Date.now()

            const { backgroundTask } = await worker.processBatch([admitted, deferred, deferredFirst])
            await backgroundTask

            expect(ran.mock.calls.map(([invocations]) => invocations)).toEqual([[{ ...admitted, queueMetadata: {} }]])
            expect(queue.deferInvocations).toHaveBeenCalledWith([
                {
                    invocation: { ...deferred, queueMetadata: { attachmentDeferrals: 3, attachmentDueAt: firstDueAt } },
                    scheduledAt: expect.any(Date),
                },
                {
                    invocation: {
                        ...deferredFirst,
                        queueMetadata: { attachmentDeferrals: 1, attachmentDueAt: firstDueAt },
                    },
                    scheduledAt: expect.any(Date),
                },
            ])
            const [[[{ scheduledAt }]]] = queue.deferInvocations.mock.calls
            expect(scheduledAt.getTime() - before).toBeGreaterThanOrEqual(10_000)
            expect(scheduledAt.getTime() - Date.now()).toBeLessThanOrEqual(20_000)
        })

        it.each([
            ['an admitted send with files until its result write settles', roomFor(1), 'queueInvocationResults'],
            ['a deferred send with files until its deferral write settles', roomFor(0), 'deferInvocations'],
        ] as const)('heartbeats %s', async (_, limits, write) => {
            const { worker, queue } = workerWith(limits, { CDP_CYCLOTRON_HEARTBEAT_INTERVAL_MS: 5 })
            const send = withFiles()
            jest.spyOn(worker, 'processInvocations').mockImplementation((invocations) =>
                Promise.resolve(resultsOf(invocations))
            )
            let finishWrite!: () => void
            queue[write].mockImplementation(() => new Promise<void>((resolve) => (finishWrite = resolve)))

            const { backgroundTask } = await worker.processBatch([send])
            await waitForExpect(() => expect(finishWrite).toBeDefined())
            const heartbeatsBeforeWrite = queue.heartbeatInvocations.mock.calls.length
            await waitForExpect(() =>
                expect(queue.heartbeatInvocations.mock.calls.length).toBeGreaterThan(heartbeatsBeforeWrite + 1)
            )
            finishWrite()
            await backgroundTask

            expect(queue.heartbeatInvocations).toHaveBeenLastCalledWith([expect.objectContaining({ id: send.id })])
        })

        it.each([
            [
                'a send with files fails while the plain sends still run',
                { send: 'fails', plain: 'ok' },
                'send failed',
                0,
            ],
            [
                'the plain sends fail while a send with files still runs',
                { send: 'ok', plain: 'fails' },
                'plain failed',
                0,
            ],
            [
                'both fail, counting the send that failed beside the batch',
                { send: 'fails later', plain: 'fails' },
                'plain failed',
                1,
            ],
        ] as const)(
            'reports the failure only once both settled when %s',
            async (_, outcomes, reported, countedBeside) => {
                const { worker, queue } = workerWith(roomFor(1))
                const [plain, send] = [job(), withFiles()]
                const kindOf = (invocation: CyclotronJobInvocation) => (invocation.id === send.id ? 'send' : 'plain')
                const writeFailures = async () =>
                    (
                        await register.getSingleMetric('cdp_cyclotron_v2_result_write_failures_total')?.get()
                    )?.values.find((sample) => sample.labels.queue === 'email')?.value ?? 0
                const failuresBefore = await writeFailures()
                let release!: () => void
                const released = new Promise<void>((resolve) => (release = resolve))
                jest.spyOn(worker, 'processInvocations').mockImplementation(async (invocations) => {
                    const kind = kindOf(invocations[0])
                    if (outcomes[kind] === 'fails') {
                        throw new Error(`${kind} failed`)
                    }
                    await released
                    if (outcomes[kind] === 'fails later') {
                        throw new Error(`${kind} failed`)
                    }
                    return resultsOf(invocations)
                })

                const batch = worker.processBatch([plain, send]).then(({ backgroundTask }) => backgroundTask)
                let settled = false
                void batch.catch(() => undefined).finally(() => (settled = true))
                await new Promise(setImmediate)
                expect(settled).toBe(false)
                release()

                await expect(batch).rejects.toThrow(reported)
                expect(written(queue)).toEqual(
                    [plain, send].filter((invocation) => outcomes[kindOf(invocation)] === 'ok').map(({ id }) => id)
                )
                expect((await writeFailures()) - failuresBefore).toBe(countedBeside)
            }
        )

        it('writes the result of a send whose abandoned call never settles before the stop deadline less its write margin, and keeps its reservation', async () => {
            jest.useFakeTimers({ doNotFake: ['setImmediate', 'nextTick'] })
            try {
                const { worker, queue } = workerWith(roomFor(1))
                const send = withFiles()
                let finishCall!: () => void
                const call = new Promise<void>((resolve) => (finishCall = resolve))
                jest.spyOn(worker, 'processInvocations').mockImplementation(async (invocations) => {
                    const deadline = new AbortController()
                    setTimeout(() => deadline.abort(new Error('deadline')), ATTACHMENT_SEND_DEADLINE_MS)
                    await settleBeforeAbortEvenWhileCredentialsStall(deadline.signal, call).catch(() => undefined)
                    return resultsOf(invocations)
                })

                const { backgroundTask } = await worker.processBatch([send])
                await new Promise(setImmediate)
                expect(written(queue)).toEqual([])
                await jest.advanceTimersByTimeAsync(CONSUMER_STOP_DEADLINE_MS - RESULT_WRITE_MARGIN_MS)
                expect(written(queue)).toEqual([send.id])
                expect((await worker.processBatch([withFiles()])).invocationResults).toEqual([])
                expect(queue.deferInvocations).toHaveBeenCalledTimes(1)

                finishCall()
                await backgroundTask
            } finally {
                jest.useRealTimers()
            }
        })

        it('reports a failed plain batch once the send beside it wrote its result, while its abandoned call still runs', async () => {
            jest.useFakeTimers({ doNotFake: ['setImmediate', 'nextTick'] })
            try {
                const { worker, queue } = workerWith(roomFor(1))
                const [plain, send] = [job(), withFiles()]
                const stalledCall = new Promise<void>(() => undefined)
                jest.spyOn(worker, 'processInvocations').mockImplementation(async (invocations) => {
                    if (invocations[0].id === plain.id) {
                        throw new Error('plain failed')
                    }
                    const deadline = new AbortController()
                    deadline.abort(new Error('deadline'))
                    await settleBeforeAbortEvenWhileCredentialsStall(deadline.signal, stalledCall).catch(
                        () => undefined
                    )
                    return resultsOf(invocations)
                })

                const batch = worker.processBatch([plain, send])
                void batch.catch(() => undefined)
                await jest.advanceTimersByTimeAsync(3_000)

                await expect(batch).rejects.toThrow('plain failed')
                expect(written(queue)).toEqual([send.id])
            } finally {
                jest.useRealTimers()
            }
        })

        const waitedTooLong = (): CyclotronJobInvocation =>
            withFiles({
                state: {
                    ...withFiles().state,
                    event: { ...createHogFlowInvocationContext().event, event: TRANSACTIONAL_EMAIL_EVENT },
                } as any,
                queueMetadata: { attachmentDeferrals: 40, attachmentDueAt: Date.now() - LONGEST_WAIT_FOR_ROOM_MS },
            })

        it.each([
            [
                'a canceled send with files on a worker that refuses files',
                null,
                () => withFiles({ cancelRequestedAt: DateTime.now() }),
                { canceled: true },
                [],
            ],
            [
                'a send with files that waited too long on workers that refuse files',
                null,
                waitedTooLong,
                { error: expect.stringContaining('attachment_wait_expired: ') },
                [expect.objectContaining({ status: 'failed', reason: 'attachment_wait_expired' })],
            ],
            [
                'a send with files that waited too long for room',
                roomFor(0),
                waitedTooLong,
                { error: expect.stringContaining('attachment_wait_expired: ') },
                [expect.objectContaining({ status: 'failed', reason: 'attachment_wait_expired' })],
            ],
        ] as const)('ends %s, instead of deferring it', async (_, limits, send, outcome, statusRows) => {
            const { worker, queue } = workerWith(limits)
            const statuses = jest.spyOn(worker['invocationResultsService'].emailStatusService, 'queue')
            const ended = send()

            await (
                await worker.processBatch([ended])
            ).backgroundTask

            expect(queue.queueInvocationResults).toHaveBeenCalledWith([
                expect.objectContaining({
                    finished: true,
                    ...outcome,
                    invocation: expect.objectContaining({ id: ended.id }),
                }),
            ])
            expect(queue.deferInvocations).not.toHaveBeenCalled()
            expect(statuses.mock.calls.map(([row]) => row).filter((row) => !row.runOutcome)).toEqual(statusRows)
        })

        const PREVIOUS_VERSION_JOB_STATE =
            '{"state":{"event":{"uuid":"uuid","event":"$pageview","elements_chain":"","distinct_id":"distinct_id","url":"http://localhost:8000/events/1","properties":{"$lib_version":"1.2.3"},"timestamp":"2026-11-09T14:31:48.377Z"},"actionStepCount":0,"send":{"tracking":{"captureEngagement":false}}}}'

        it.each([
            [
                'a send larger than one email can carry, where it fails,',
                () =>
                    withFiles({
                        state: {
                            ...createHogFlowInvocationContext(),
                            send: {
                                attachments: [
                                    {
                                        filename: 'archive.zip',
                                        sha256: 'b'.repeat(64),
                                        sizeBytes: LARGEST_SEND_FILE_BYTES + 1,
                                    },
                                ],
                            },
                        } as any,
                    }),
            ],
            [
                'a job that the previous version stored',
                () =>
                    v2JobToInvocation({
                        id: new UUIDT().toString(),
                        teamId: 1,
                        functionId: new UUIDT().toString(),
                        queueName: 'email',
                        priority: 0,
                        scheduled: DateTime.now(),
                        created: DateTime.now(),
                        state: Buffer.from(PREVIOUS_VERSION_JOB_STATE),
                    } as unknown as CyclotronV2DequeuedJob),
            ],
        ])('runs %s in its batch on a worker that refuses files, instead of deferring it', async (_, invocation) => {
            const { worker, queue } = workerWith(null)
            const job = invocation()
            const ran = jest
                .spyOn(worker, 'processInvocations')
                .mockImplementation((invocations) => Promise.resolve(resultsOf(invocations)))

            await (
                await worker.processBatch([job])
            ).backgroundTask

            expect(ran).toHaveBeenCalledWith([job])
            expect(queue.deferInvocations).not.toHaveBeenCalled()
        })

        it('holds no more than its budget under a burst, and sends every one without failing any', async () => {
            const { worker, queue } = workerWith({ ...roomFor(3), maxInFlight: 10 })
            const budgetBytes = roomFor(3).budgetBytes
            const due = Array.from({ length: 20 }, () => withFiles())
            const sent = new Set<string>()
            let reservedBytes = 0
            let peakReservedBytes = 0
            jest.spyOn(worker, 'processInvocations').mockImplementation(async (invocations) => {
                reservedBytes += estimateSend(FILE_BYTES).reservedBytes
                peakReservedBytes = Math.max(peakReservedBytes, reservedBytes)
                await new Promise(setImmediate)
                reservedBytes -= estimateSend(FILE_BYTES).reservedBytes
                invocations.forEach((invocation) => sent.add(invocation.id))
                return resultsOf(invocations)
            })
            queue.deferInvocations.mockImplementation((deferrals) => {
                due.push(...deferrals.map(({ invocation }) => invocation))
                return Promise.resolve()
            })

            const backgroundTasks: Promise<unknown>[] = []
            for (let dequeue = 0; dequeue < 100 && sent.size < 20; dequeue++) {
                const batch = due.splice(0, 5)
                backgroundTasks.push((await worker.processBatch(batch)).backgroundTask)
                await new Promise(setImmediate)
            }
            await Promise.all(backgroundTasks)

            expect(sent.size).toBe(20)
            expect(peakReservedBytes).toBe(budgetBytes)
            expect(written(queue)).toHaveLength(20)
            expect(due).toEqual([])
        })
    })
})
