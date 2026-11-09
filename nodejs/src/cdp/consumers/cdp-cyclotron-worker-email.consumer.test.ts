import { createMockJobQueue } from '~/tests/helpers/mocks/job-queue.mock'

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
import { InFlightLimits, InFlightRegistry, estimateSend } from '../services/messaging/in-flight-registry'
import { CyclotronJobInvocation, CyclotronJobInvocationResult } from '../types'
import { createInvocationResult } from '../utils/invocation-utils'
import { CdpCyclotronWorkerEmail } from './cdp-cyclotron-worker-email.consumer'

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

        const workerWith = (limits: InFlightLimits, config: Partial<Hub> = {}) => {
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

        it('defers the sends it has no room for, with one more deferral and a longer delay', async () => {
            const { worker, queue } = workerWith({ ...roomFor(5), maxInFlight: 1 })
            const [admitted, deferred] = [
                withFiles({ queueMetadata: { attachmentDeferrals: 1 } }),
                withFiles({ queueMetadata: { attachmentDeferrals: 2 } }),
            ]
            const ran = jest
                .spyOn(worker, 'processInvocations')
                .mockImplementation((invocations) => Promise.resolve(resultsOf(invocations)))
            const before = Date.now()

            const { backgroundTask } = await worker.processBatch([admitted, deferred])
            await backgroundTask

            expect(ran.mock.calls.map(([invocations]) => invocations)).toEqual([[{ ...admitted, queueMetadata: {} }]])
            expect(queue.deferInvocations).toHaveBeenCalledWith([
                {
                    invocation: { ...deferred, queueMetadata: { attachmentDeferrals: 3 } },
                    scheduledAt: expect.any(Date),
                },
            ])
            const [[[{ scheduledAt }]]] = queue.deferInvocations.mock.calls
            expect(scheduledAt.getTime() - before).toBeGreaterThanOrEqual(10_000)
            expect(scheduledAt.getTime() - Date.now()).toBeLessThanOrEqual(20_000)
        })

        it('heartbeats a send with files until its result write settles', async () => {
            const { worker, queue } = workerWith(roomFor(1), { CDP_CYCLOTRON_HEARTBEAT_INTERVAL_MS: 5 })
            const send = withFiles()
            jest.spyOn(worker, 'processInvocations').mockImplementation((invocations) =>
                Promise.resolve(resultsOf(invocations))
            )
            let finishWrite!: () => void
            queue.queueInvocationResults.mockImplementation(() => new Promise((resolve) => (finishWrite = resolve)))

            const { backgroundTask } = await worker.processBatch([send])
            await waitForExpect(() => expect(finishWrite).toBeDefined())
            const heartbeatsBeforeWrite = queue.heartbeatInvocations.mock.calls.length
            await waitForExpect(() =>
                expect(queue.heartbeatInvocations.mock.calls.length).toBeGreaterThan(heartbeatsBeforeWrite + 1)
            )
            finishWrite()
            await backgroundTask

            expect(queue.heartbeatInvocations).toHaveBeenLastCalledWith([send])
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
