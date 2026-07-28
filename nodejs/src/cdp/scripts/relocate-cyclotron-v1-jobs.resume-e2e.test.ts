/**
 * End-to-end proof that a hogflow job relocated from cyclotron V1 -> V2 by the operator
 * script actually RESUMES and advances in V2 — not just that a row lands in the table.
 *
 * Chain exercised, all real except `fetch`:
 *   V1 producer serializes a parked-on-delay hogflow invocation into test_cyclotron
 *     -> relocate() (the script under test) moves it to test_cyclotron_node
 *     -> CdpCyclotronWorkerHogFlow polls V2 -> HogFlowExecutorService resumes the delay
 *     -> next action (fetch) fires -> workflow completes.
 *
 * This is the regression the row-shape tests can't catch: a payload that lands structurally
 * intact but is not executable (wrong state shape, missing currentAction) would pass every
 * "did the row land" assertion yet silently never resume in production.
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
import { insertHogFunctionTemplate } from '../_tests/fixtures'
import { insertHogFlow } from '../_tests/fixtures-hogflows'
import { CdpCyclotronWorkerHogFlow } from '../consumers/cdp-cyclotron-worker-hogflow.consumer'
import { CyclotronJobQueuePostgres } from '../services/job-queue/job-queue-postgres'
import { CyclotronJobQueuePostgresV2 } from '../services/job-queue/job-queue-postgres-v2'
import { CyclotronJobInvocationHogFlow } from '../types'
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

        const deps = {
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
})
