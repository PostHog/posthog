/**
 * End-to-end proof that a hogflow job relocated from cyclotron V1 -> V2 by the operator
 * script actually RESUMES and advances in V2 — not just that a row lands in the table.
 *
 * Two parked-wait shapes, both seeded into V1 via the real V1 producer, relocated with the
 * real relocate(), then executed by the real CdpCyclotronWorkerHogFlow polling V2:
 *   1. delay: comes due on a schedule -> resumes to the next action -> completes.
 *   2. wait_until_condition: woken by the subscription matcher on a matching event. The matcher
 *      finds parked jobs by the V2 `distinct_id`/`person_id` lookup columns, so this proves
 *      relocation populates them — a relocated event-wait that lost those columns would be
 *      invisible to the matcher and silently never wake (the failure mode a row-shape check misses).
 */
import { mockFetch } from '~/tests/helpers/mocks/request.mock'

import { DateTime } from 'luxon'
import { Pool } from 'pg'

import { closeHub, createHub } from '~/common/utils/db/hub'
import { UUIDT } from '~/common/utils/utils'
import { createCdpConsumerDeps } from '~/tests/helpers/cdp'
import { waitForExpect } from '~/tests/helpers/expectations'
import { TEST_KAFKA_TOPICS, ensureKafkaTopics } from '~/tests/helpers/kafka'
import { getFirstTeam, resetTestDatabase } from '~/tests/helpers/sql'

import { KafkaProducerWrapper } from '../../common/kafka/producer'
import { Hub, Team } from '../../types'
import { FixtureHogFlowBuilder } from '../_tests/builders/hogflow.builder'
import { HOG_FILTERS_EXAMPLES } from '../_tests/examples'
import { createHogExecutionGlobals, insertHogFunctionTemplate } from '../_tests/fixtures'
import { insertHogFlow } from '../_tests/fixtures-hogflows'
import { CdpCyclotronWorkerHogFlow } from '../consumers/cdp-cyclotron-worker-hogflow.consumer'
import { CdpHogflowSubscriptionMatcherConsumer } from '../consumers/cdp-hogflow-subscription-matcher.consumer'
import { CyclotronJobQueuePostgres } from '../services/job-queue/job-queue-postgres'
import { CyclotronJobQueuePostgresV2 } from '../services/job-queue/job-queue-postgres-v2'
import { CyclotronJobInvocationHogFlow, HogFunctionInvocationGlobals } from '../types'
import { convertBatchHogFlowRequestToHogFunctionInvocationGlobals } from '../utils'
import { convertToHogFunctionFilterGlobal } from '../utils/hog-function-filtering'
import { relocate } from './relocate-cyclotron-v1-jobs'

const ActualKafkaProducerWrapper = jest.requireActual('~/common/kafka/producer').KafkaProducerWrapper

const V1_DB_URL = process.env.CYCLOTRON_DATABASE_URL ?? 'postgres://posthog:posthog@localhost:5432/test_cyclotron'
const V2_DB_URL =
    process.env.CYCLOTRON_NODE_DATABASE_URL ?? 'postgres://posthog:posthog@localhost:5432/test_cyclotron_node'

describe('relocate-cyclotron-v1-jobs resume (e2e)', () => {
    jest.setTimeout(30000)

    let hub: Hub
    let kafkaProducer: KafkaProducerWrapper
    let team: Team
    let v1Pool: Pool
    let v2Pool: Pool
    let v1Producer: CyclotronJobQueuePostgres
    let v2RelocateProducer: CyclotronJobQueuePostgresV2
    let worker: CdpCyclotronWorkerHogFlow
    let deps: ReturnType<typeof createCdpConsumerDeps>

    beforeEach(async () => {
        await ensureKafkaTopics(TEST_KAFKA_TOPICS)
        await resetTestDatabase()

        v1Pool = new Pool({ connectionString: V1_DB_URL })
        v2Pool = new Pool({ connectionString: V2_DB_URL })
        await v1Pool.query(`DELETE FROM cyclotron_jobs`)
        await v2Pool.query(`DELETE FROM cyclotron_jobs`)

        hub = await createHub()
        hub.CDP_CYCLOTRON_BATCH_DELAY_MS = 50
        kafkaProducer = await ActualKafkaProducerWrapper.create(hub.KAFKA_CLIENT_RACK)
        team = await getFirstTeam(hub.postgres)

        await insertHogFunctionTemplate(hub.postgres, {
            id: 'template-relocate-resume-fetch',
            name: 'Relocate Resume Fetch',
            code: `let res := fetch(inputs.url, {'method': inputs.method}); print('Fetch result:', res.status);`,
            inputs_schema: [
                { key: 'url', type: 'string', required: true },
                { key: 'method', type: 'string', required: false },
            ],
        })

        deps = {
            ...createCdpConsumerDeps(hub, kafkaProducer),
            personRepository: {
                fetchPerson: jest.fn().mockResolvedValue(undefined),
                fetchPersonsByDistinctIds: jest.fn().mockResolvedValue([]),
                fetchPersonsByPersonIds: jest.fn().mockResolvedValue([]),
                fetchDistinctIdsForPersons: jest.fn().mockResolvedValue({}),
            } as any,
        }

        // V1 producer to seed a realistic parked row; a separate V2 producer for the script;
        // the worker consumes V2 on its own queue instance.
        v1Producer = new CyclotronJobQueuePostgres(hub.CONSUMER_BATCH_SIZE, hub)
        v2RelocateProducer = new CyclotronJobQueuePostgresV2(1, hub)
        const workerQueue = new CyclotronJobQueuePostgresV2(hub.CONSUMER_BATCH_SIZE, hub)
        await v1Producer.startAsProducer()

        worker = new CdpCyclotronWorkerHogFlow(hub, deps, workerQueue)
        await worker.start()

        mockFetch.mockResolvedValue({
            status: 200,
            headers: { 'Content-Type': 'application/json' },
            json: () => Promise.resolve({ success: true }),
            text: () => Promise.resolve(JSON.stringify({ success: true })),
            dump: () => Promise.resolve(),
        } as any)
    })

    afterEach(async () => {
        await worker?.stop().catch(() => undefined)
        await v1Producer?.stopProducer().catch(() => undefined)
        await v2RelocateProducer?.stopProducer().catch(() => undefined)
        await kafkaProducer?.disconnect().catch(() => undefined)
        await closeHub(hub).catch(() => undefined)
        await v1Pool?.end().catch(() => undefined)
        await v2Pool?.end().catch(() => undefined)
    })

    it('a job parked on a delay in V1 resumes and completes after relocation to V2', async () => {
        // trigger -> delay -> fetch -> exit, active for this team.
        const flow = new FixtureHogFlowBuilder()
            .withTeamId(team.id)
            .withStatus('active')
            .withWorkflow({
                actions: {
                    trigger: {
                        type: 'trigger',
                        config: { type: 'event', filters: HOG_FILTERS_EXAMPLES.no_filters.filters ?? {} },
                    },
                    delay_1: { type: 'delay', config: { delay_duration: '1s' } },
                    function_1: {
                        type: 'function',
                        config: {
                            template_id: 'template-relocate-resume-fetch',
                            inputs: {
                                url: { value: 'https://example.com/relocated-webhook' },
                                method: { value: 'POST' },
                            },
                        },
                    },
                    exit: { type: 'exit', config: {} },
                },
                edges: [
                    { from: 'trigger', to: 'delay_1', type: 'continue' },
                    { from: 'delay_1', to: 'function_1', type: 'continue' },
                    { from: 'function_1', to: 'exit', type: 'continue' },
                ],
            })
            .build()
        await insertHogFlow(hub.postgres, flow)

        // A realistic parked-on-delay invocation: currentAction sits on the delay node with a
        // startedAtTimestamp far enough in the past that the 1s delay is already elapsed, and a
        // future queueScheduledAt (the delay's wake time) so it's parked, exactly like prod.
        const personUuid = new UUIDT().toString()
        const invocationGlobals = convertBatchHogFlowRequestToHogFunctionInvocationGlobals({
            team,
            personId: personUuid,
            siteUrl: hub.SITE_URL,
        })
        const parked: CyclotronJobInvocationHogFlow = {
            id: new UUIDT().toString(),
            state: {
                event: invocationGlobals.event,
                personId: personUuid,
                actionStepCount: 1,
                currentAction: { id: 'delay_1', startedAtTimestamp: Date.now() - 2 * 24 * 60 * 60 * 1000 },
                variables: {},
            },
            teamId: team.id,
            functionId: flow.id,
            parentRunId: new UUIDT().toString(),
            hogFlow: flow,
            person: invocationGlobals.person,
            filterGlobals: convertToHogFunctionFilterGlobal(invocationGlobals),
            queue: 'hogflow',
            queuePriority: 1,
            queueScheduledAt: DateTime.utc().plus({ days: 30 }),
        } as CyclotronJobInvocationHogFlow

        await v1Producer.queueInvocations([parked])

        // Present in V1, absent from V2, before relocation.
        expect(
            (await v1Pool.query(`SELECT id FROM cyclotron_jobs WHERE queue_name='hogflow' AND state='available'`)).rows
        ).toHaveLength(1)
        expect((await v2Pool.query(`SELECT id FROM cyclotron_jobs WHERE queue_name='hogflow'`)).rows).toHaveLength(0)

        // Run the actual relocation script.
        const result = await relocate(
            { v1: v1Pool, v2Pool, v2Queue: v2RelocateProducer },
            { queue: 'hogflow', envLabel: 'test', apply: true }
        )
        expect(result).toMatchObject({ relocated: 1, deletedCorrupt: 0, remaining: 0, missingIds: [] })

        // V1 drained; the row is now in V2 but still parked (future schedule) — fetch must NOT fire yet.
        expect(
            (await v1Pool.query(`SELECT id FROM cyclotron_jobs WHERE queue_name='hogflow' AND state='available'`)).rows
        ).toHaveLength(0)
        expect((await v2Pool.query(`SELECT id FROM cyclotron_jobs WHERE queue_name='hogflow'`)).rows).toHaveLength(1)
        expect(mockFetch).not.toHaveBeenCalled()

        // The delay comes due (same scheduled-time bump the scheduler would do). The worker picks
        // the relocated job up, the elapsed delay advances to the fetch step, and the flow completes.
        await v2Pool.query(
            `UPDATE cyclotron_jobs SET scheduled = NOW() WHERE queue_name='hogflow' AND status='available' AND scheduled > NOW()`
        )

        await waitForExpect(() => {
            expect(mockFetch).toHaveBeenCalledTimes(1)
        }, 15000)
        expect(mockFetch).toHaveBeenCalledWith(
            'https://example.com/relocated-webhook',
            expect.objectContaining({ method: 'POST' })
        )

        await waitForExpect(async () => {
            const terminal = await v2Pool.query(
                `SELECT id FROM cyclotron_jobs WHERE queue_name='hogflow' AND status='completed'`
            )
            expect(terminal.rows).toHaveLength(1)
        }, 5000)
    })

    // Mirrors what Django compiles for a single-event wait entry {events: [{id: <name>}]}.
    const eventNameFilter = (eventName: string) => ({
        filters: { events: [{ id: eventName }], bytecode: ['_H', 1, 32, eventName, 32, 'event', 1, 1, 11] },
    })

    const buildGlobals = (eventName: string, distinctId: string): HogFunctionInvocationGlobals =>
        createHogExecutionGlobals({
            project: { id: team.id } as any,
            event: {
                uuid: new UUIDT().toString(),
                event: eventName,
                distinct_id: distinctId,
                properties: { $current_url: 'https://posthog.com' },
                timestamp: '2024-09-03T09:00:00Z',
            } as any,
        })

    it('a wait_until_condition job relocated from V1 is woken by the subscription matcher in V2', async () => {
        // trigger -> wait_condition -> (matched branch | timeout continue) -> exit.
        // Condition never matches the trigger event, so the job parks; the wake comes from a
        // subscribed 'wakeup_event', which the matcher can only see for a job living in V2.
        const flow = new FixtureHogFlowBuilder()
            .withTeamId(team.id)
            .withStatus('active')
            .withWorkflow({
                actions: {
                    trigger: {
                        type: 'trigger',
                        config: { type: 'event', filters: HOG_FILTERS_EXAMPLES.no_filters.filters ?? {} },
                    },
                    wait_condition: {
                        type: 'wait_until_condition',
                        config: {
                            condition: { filters: HOG_FILTERS_EXAMPLES.elements_text_filter.filters },
                            events: [eventNameFilter('wakeup_event')],
                            max_wait_duration: '5m',
                        },
                    },
                    function_matched: {
                        type: 'function',
                        config: {
                            template_id: 'template-relocate-resume-fetch',
                            inputs: {
                                url: { value: 'https://example.com/condition-matched' },
                                method: { value: 'POST' },
                            },
                        },
                    },
                    function_timeout: {
                        type: 'function',
                        config: {
                            template_id: 'template-relocate-resume-fetch',
                            inputs: {
                                url: { value: 'https://example.com/timed-out' },
                                method: { value: 'POST' },
                            },
                        },
                    },
                    exit: { type: 'exit', config: {} },
                },
                edges: [
                    { from: 'trigger', to: 'wait_condition', type: 'continue' },
                    { from: 'wait_condition', to: 'function_matched', type: 'branch', index: 0 },
                    { from: 'wait_condition', to: 'function_timeout', type: 'continue' },
                    { from: 'function_matched', to: 'exit', type: 'continue' },
                    { from: 'function_timeout', to: 'exit', type: 'continue' },
                ],
            })
            .build()
        await insertHogFlow(hub.postgres, flow)

        // Parked on the wait node: currentAction on wait_condition, started recently (well within
        // the 5m cap so it's genuinely waiting, not timed out), a known distinct_id so the matcher
        // can find it, and a future queueScheduledAt (the polling cap) so it's parked.
        const distinctId = 'wait-relocate-user'
        const globals = buildGlobals('$pageview', distinctId)
        const parked: CyclotronJobInvocationHogFlow = {
            id: new UUIDT().toString(),
            state: {
                event: globals.event,
                actionStepCount: 1,
                currentAction: { id: 'wait_condition', startedAtTimestamp: Date.now() - 60 * 1000 },
                variables: {},
            },
            teamId: team.id,
            functionId: flow.id,
            parentRunId: new UUIDT().toString(),
            hogFlow: flow,
            person: globals.person,
            filterGlobals: convertToHogFunctionFilterGlobal(globals),
            queue: 'hogflow',
            queuePriority: 1,
            queueScheduledAt: DateTime.utc().plus({ minutes: 2 }),
        } as CyclotronJobInvocationHogFlow

        await v1Producer.queueInvocations([parked])

        const result = await relocate(
            { v1: v1Pool, v2Pool, v2Queue: v2RelocateProducer },
            { queue: 'hogflow', envLabel: 'test', apply: true }
        )
        expect(result).toMatchObject({ relocated: 1, remaining: 0, missingIds: [] })

        // The lookup column the matcher queries on must be populated by relocation — otherwise the
        // matcher can't find the job and it never wakes.
        const relocated = await v2Pool.query(
            `SELECT distinct_id FROM cyclotron_jobs WHERE queue_name='hogflow' AND status='available'`
        )
        expect(relocated.rows).toHaveLength(1)
        expect(relocated.rows[0].distinct_id).toBe(distinctId)
        expect(mockFetch).not.toHaveBeenCalled()

        // The subscribed event fires for this person; the matcher finds the relocated V2 job by its
        // lookup column, marks it matched + due, and the worker resumes it onto the matched branch.
        const matcher = new CdpHogflowSubscriptionMatcherConsumer({ ...hub }, deps)
        try {
            await matcher.processBatch([buildGlobals('wakeup_event', distinctId)])

            await waitForExpect(() => {
                expect(mockFetch).toHaveBeenCalledTimes(1)
            }, 15000)
            expect(mockFetch).toHaveBeenCalledWith(
                'https://example.com/condition-matched',
                expect.objectContaining({ method: 'POST' })
            )
        } finally {
            await matcher.stop().catch(() => undefined)
        }
    })
})
