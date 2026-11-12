// Serial: resets shared Postgres and relies on the reset-created default team.
import { createMockJobQueue } from '../../tests/helpers/mocks/job-queue.mock'
import { mockFetch } from '../../tests/helpers/mocks/request.mock'

import { KafkaProducerObserver } from '~/tests/helpers/mocks/producer.spy'

import { Server } from 'http'
import jwt from 'jsonwebtoken'
import { DateTime } from 'luxon'
import { createHash, randomBytes, randomUUID } from 'node:crypto'
import { Pool } from 'pg'
import pino from 'pino'
import { Counter, register } from 'prom-client'
import supertest from 'supertest'
import express from 'ultimate-express'

import { CyclotronInputType } from '~/cdp/schema/cyclotron'
import { HogFlow } from '~/cdp/schema/hogflow'
import { PosthogJwtAudience } from '~/cdp/utils/jwt-utils'
import { ScopedServiceJwt } from '~/cdp/utils/scoped-service-jwt'
import { setupExpressApp } from '~/common/api/router'
import { KafkaProducerWrapper } from '~/common/kafka/producer'
import { PersonReadRepository } from '~/common/persons/repositories/person-repository'
import { PostgresPersonRepository } from '~/common/persons/repositories/postgres-person-repository'
import { deleteKeysWithPrefix } from '~/common/redis/_tests/redis'
import { RedisV2, createRedisV2PoolFromConfig } from '~/common/redis/redis-v2'
import { closeHub, createHub } from '~/common/utils/db/hub'
import { PostgresRouter, PostgresUse } from '~/common/utils/db/postgres'
import { parseJSON } from '~/common/utils/json-parse'
import { logger } from '~/common/utils/logger'
import { UUIDT } from '~/common/utils/utils'
import { waitForExpect } from '~/tests/helpers/expectations'

import { createCdpConsumerDeps } from '../../tests/helpers/cdp'
import { forSnapshot } from '../../tests/helpers/snapshots'
import { createTeam, getFirstTeam, resetTestDatabase } from '../../tests/helpers/sql'
import { Hub, Team } from '../types'
import { FixtureHogFlowBuilder, SimpleHogFlowRepresentation } from './_tests/builders/hogflow.builder'
import {
    BucketProxy,
    EmailQueueOfOneTest,
    HeldQuery,
    PostgresProxy,
    StoredFile,
    attachmentFile,
    attachmentStoreConfig,
    deliveredTo,
    sesClientFor,
    uploadAttachment,
} from './_tests/email-delivery-fakes'
import { HOG_EXAMPLES, HOG_FILTERS_EXAMPLES, HOG_INPUTS_EXAMPLES } from './_tests/examples'
import { startFakeSes } from './_tests/fake-ses'
import {
    insertHogFunction as _insertHogFunction,
    createHogFunction,
    insertHogFunctionTemplate,
    insertIntegration,
} from './_tests/fixtures'
import { insertHogFlow as _insertHogFlow, hideHogFlowsFromReplica } from './_tests/fixtures-hogflows'
import { CdpApi } from './cdp-api'
import { getDefaultCdpConfig } from './config'
import { CdpConsumerBaseDeps } from './consumers/cdp-base.consumer'
import { CdpCyclotronWorkerEmail } from './consumers/cdp-cyclotron-worker-email.consumer'
import { posthogFilterOutPlugin } from './legacy-plugins/_transformations/posthog-filter-out-plugin/template'
import { CyclotronV2Manager, CyclotronV2Worker } from './services/cyclotron-v2'
import { CyclotronV2JobProducer } from './services/cyclotron-v2/types'
import { IdempotencyKeys, createIdempotencyValkeyPool } from './services/hogflows/idempotency-keys'
import {
    ATTACHMENT_CONTENT_ID_MAX_LENGTH,
    ATTACHMENT_CONTENT_TYPE_MAX_LENGTH,
    ATTACHMENT_FILENAME_MAX_LENGTH,
    transactionalEmailRequestsTotal,
    transactionalEmailStageDurationMs,
} from './services/hogflows/transactional-email'
import { CyclotronJobQueuePostgresV2 } from './services/job-queue/job-queue-postgres-v2'
import { SEND_NEEDS_FILES_FOR_MS } from './services/messaging/attachment-horizon'
import {
    ATTACHMENT_LIFETIME_MS,
    DAY_MS,
    S3AttachmentStore,
    buildAttachmentStore,
} from './services/messaging/attachment-store'
import { ATTACHMENT_VERIFICATION_DEADLINE_MS, AttachmentUploads } from './services/messaging/attachment-uploads'
import { SuppressionLookupError } from './services/messaging/email-suppression.service'
import { UTM_VALUE_LIMIT_CHARS } from './services/messaging/helpers/utm'
import { InFlightRegistry } from './services/messaging/in-flight-registry'
import { MESSAGE_MAX_BYTES, estimateMessageBytes } from './services/messaging/message-estimate'
import {
    HOG_FLOW_VERSION_APP_SOURCE,
    versionedAppSourceId,
} from './services/monitoring/hog-function-monitoring.service'
import { BASE_REDIS_KEY, HogWatcherState } from './services/monitoring/hog-watcher.service'
import { template as emailTemplate } from './templates/_destinations/email/email.template'
import { compileHog } from './templates/compiler'
import { HogFunctionInvocationGlobals, HogFunctionType } from './types'
import { EMAIL_BODY_TAG_LIMIT, LIQUID_RENDER_LIMIT_MS } from './utils/liquid'

// Email MX validation runs on every email send, so without a mock the test-panel
// email tests would do live DNS lookups for their fixture recipients (and
// example.com publishes a null MX, which validation correctly blocks). Resolve
// everything as deliverable — validation behavior is covered by
// email-validation.service.test.ts.
jest.mock('node:dns/promises', () => ({
    Resolver: jest.fn().mockImplementation(() => ({
        resolveMx: jest.fn().mockResolvedValue([{ exchange: 'mx.example.com', priority: 10 }]),
        resolve4: jest.fn().mockResolvedValue(['1.2.3.4']),
        resolve6: jest.fn().mockResolvedValue([]),
    })),
}))

const fakeJobProducer = (overrides: Partial<CyclotronV2JobProducer> = {}): CyclotronV2JobProducer => ({
    createJob: jest.fn(),
    countInFlightJobs: jest.fn(),
    rescheduleParkedJobs: jest.fn(),
    cancelJobs: jest.fn(),
    resumeParkedSteps: jest.fn(),
    resumeParkedBatchResolver: jest.fn(),
    cancelUnclaimed: jest.fn(),
    rescheduleUnclaimed: jest.fn(),
    disconnect: jest.fn().mockResolvedValue(undefined),
    ...overrides,
})

const emittedLogLines = (): { lines: string[]; stop: () => void } => {
    const target = logger as unknown as { pino: pino.Logger }
    const original = target.pino
    const lines: string[] = []
    target.pino = pino({ level: 'debug' }, { write: (line: string) => void lines.push(line) })
    return {
        lines,
        stop: () => {
            target.pino = original
        },
    }
}
describe('CDP API', () => {
    let hub: Hub
    let cdpDeps: CdpConsumerBaseDeps
    let team: Team
    let app: express.Application
    let server: Server
    let api: CdpApi
    let hogFunction: HogFunctionType
    let hogFunctionMultiFetch: HogFunctionType

    const globals: Partial<HogFunctionInvocationGlobals> = {
        groups: {},
        person: {
            id: '123',
            name: 'Jane Doe',
            url: 'https://example.com/person/123',
            properties: {
                email: 'example@posthog.com',
            },
        },
        event: {
            uuid: 'b3a1fe86-b10c-43cc-acaf-d208977608d0',
            event: '$pageview',
            elements_chain: '',
            distinct_id: '123',
            timestamp: '2021-09-28T14:00:00Z',
            url: 'https://example.com/events/b3a1fe86-b10c-43cc-acaf-d208977608d0/2021-09-28T14:00:00Z',
            properties: {
                $lib_version: '1.0.0',
            },
        },
    }

    const insertHogFunction = async (hogFunction: Partial<HogFunctionType>) => {
        const item = await _insertHogFunction(hub.postgres, team.id, hogFunction)
        // Trigger the reload that django would do
        api['hogFunctionManager']['onHogFunctionsReloaded'](team.id, [item.id])
        return item
    }

    const insertHogFlow = async (hogFlow: Partial<HogFlow>) => {
        const item = await _insertHogFlow(hub.postgres, { team_id: team.id, ...hogFlow } as HogFlow)
        // Trigger the reload that django would do
        api['hogFlowManager']['onHogFlowsReloaded'](team.id, [item.id])
        return item
    }

    beforeAll(async () => {
        // Reset before caching the team: without this, getFirstTeam picks up
        // whatever team the previous suite left with the lowest id, and every
        // beforeEach reset then deletes it — inserts against the cached team
        // id fail on the team FK.
        await resetTestDatabase()
        hub = await createHub({
            SITE_URL: 'http://localhost:8000',
        })
        hub.CDP_GOOGLE_ADWORDS_DEVELOPER_TOKEN = 'ADWORDS_TOKEN'
        team = await getFirstTeam(hub.postgres)

        cdpDeps = createCdpConsumerDeps(hub)
        api = new CdpApi(
            hub,
            { ...cdpDeps, idempotencyValkey: createIdempotencyValkeyPool(hub) },
            {
                hogQueue: createMockJobQueue(),
                hogflowQueue: createMockJobQueue(),
            }
        )
        app = setupExpressApp()
        app.use('/', api.router())
        server = app.listen(0, () => {})
    })

    beforeEach(async () => {
        await resetTestDatabase()

        mockFetch.mockClear()

        hogFunction = await insertHogFunction({
            name: 'test hog function',
            ...HOG_EXAMPLES.simple_fetch,
            ...HOG_INPUTS_EXAMPLES.simple_fetch,
            ...HOG_FILTERS_EXAMPLES.no_filters,
        })

        hogFunctionMultiFetch = await insertHogFunction({
            name: 'test hog function multi fetch',
            ...HOG_EXAMPLES.recursive_fetch,
            ...HOG_INPUTS_EXAMPLES.simple_fetch,
            ...HOG_FILTERS_EXAMPLES.no_filters,
        })
    })

    afterAll(async () => {
        server.close()
        await closeHub(hub)
    })

    it('errors if missing hog function', async () => {
        const res = await supertest(app)
            .post(`/api/projects/${hogFunction.team_id}/hog_functions/${new UUIDT().toString()}/invocations`)
            .send({ globals })

        expect(res.status).toEqual(404)
    })

    it('errors if missing team', async () => {
        const res = await supertest(app)
            .post(`/api/projects/${new UUIDT().toString()}/hog_functions/${hogFunction.id}/invocations`)
            .send({ globals })

        expect(res.status).toEqual(404)
    })

    it.each([
        ['nothing at all', {}],
        ['an empty clickhouse_event', { clickhouse_event: {} }],
        ['a clickhouse_event with no timestamp', { clickhouse_event: { event: '$pageview' } }],
        ['a clickhouse_event with a numeric timestamp', { clickhouse_event: { event: '$pageview', timestamp: 1 } }],
        [
            'a clickhouse_event with an unparseable timestamp',
            { clickhouse_event: { event: '$pageview', timestamp: 'not-a-date' } },
        ],
    ])('errors if the body carries %s', async (_name, body) => {
        const res = await supertest(app)
            .post(`/api/projects/${hogFunction.team_id}/hog_functions/${hogFunction.id}/invocations`)
            .send(body)

        expect(res.status).toEqual(400)
        expect(res.body).toEqual({
            error: 'Missing event',
        })
    })

    it('still converts a clickhouse_event that has a timestamp but no event name', async () => {
        const res = await supertest(app)
            .post(`/api/projects/${hogFunction.team_id}/hog_functions/${hogFunction.id}/invocations`)
            .send({
                clickhouse_event: { uuid: new UUIDT().toString(), timestamp: '2021-09-28 14:00:00.000' },
                mock_async_functions: true,
            })

        expect(res.status).toEqual(200)
    })

    it('uses the given globals when clickhouse_event carries no event', async () => {
        const res = await supertest(app)
            .post(`/api/projects/${hogFunction.team_id}/hog_functions/${hogFunction.id}/invocations`)
            .send({ globals, clickhouse_event: {}, mock_async_functions: true })

        expect(res.status).toEqual(200)
        expect(res.body.errors).toEqual([])
    })

    it("does not error if hog function is 'new'", async () => {
        const res = await supertest(app)
            .post(`/api/projects/${hogFunction.team_id}/hog_functions/new/invocations`)
            .send({ globals })

        expect(res.status).toEqual(400)
    })

    it('can invoke a function via the API with mocks', async () => {
        const res = await supertest(app)
            .post(`/api/projects/${hogFunction.team_id}/hog_functions/${hogFunction.id}/invocations`)
            .send({ globals, mock_async_functions: true })

        expect(res.status).toEqual(200)
        expect(res.body.errors).toEqual([])
        expect(res.body.logs.map((log: any) => log.message).slice(0, -1)).toMatchInlineSnapshot(`
            [
              "Async function 'fetch' was mocked with arguments:",
              "fetch('https://example.com/posthog-webhook', {
              "headers": {
                "version": "v=1.0.0"
              },
              "body": {
                "event": {
                  "uuid": "b3a1fe86-b10c-43cc-acaf-d208977608d0",
                  "event": "$pageview",
                  "elements_chain": "",
                  "distinct_id": "123",
                  "timestamp": "2021-09-28T14:00:00Z",
                  "url": "https://example.com/events/b3a1fe86-b10c-43cc-acaf-d208977608d0/2021-09-28T14:00:00Z",
                  "properties": {
                    "$lib_version": "1.0.0"
                  }
                },
                "groups": {},
                "nested": {
                  "foo": "https://example.com/events/b3a1fe86-b10c-43cc-acaf-d208977608d0/2021-09-28T14:00:00Z"
                },
                "person": {
                  "id": "123",
                  "name": "Jane Doe",
                  "url": "https://example.com/person/123",
                  "properties": {
                    "email": "example@posthog.com"
                  }
                },
                "event_url": "https://example.com/events/b3a1fe86-b10c-43cc-acaf-d208977608d0/2021-09-28T14:00:00Z-test"
              },
              "method": "POST"
            })",
              "Fetch response:, {"status":200,"body":{}}",
            ]
        `)
    })

    it('keeps the server project when the request globals carry a different one', async () => {
        const res = await supertest(app)
            .post(`/api/projects/${hogFunction.team_id}/hog_functions/${hogFunction.id}/invocations`)
            .send({
                globals: {
                    ...globals,
                    project: { id: 999, name: 'Placeholder', url: 'https://example.com/project/999' },
                },
                mock_async_functions: true,
                configuration: {
                    inputs: {
                        ...hogFunction.inputs,
                        body: {
                            value: { project_url: '{project.url}' },
                            bytecode: { project_url: ['_H', 1, 32, 'url', 32, 'project', 1, 2] },
                        },
                    },
                },
            })

        expect(res.status).toEqual(200)
        expect(res.body.errors).toEqual([])
        const fetchLog = res.body.logs.map((log: any) => log.message).join('\n')
        expect(fetchLog).toContain(`"project_url": "http://localhost:8000/project/${team.id}"`)
        expect(fetchLog).not.toContain('/project/999')
    })

    it('can invoke a function via the API with real fetch', async () => {
        mockFetch.mockImplementationOnce(() =>
            Promise.resolve({
                status: 201,
                headers: { 'Content-Type': 'application/json' },
                json: () => Promise.resolve({ real: true }),
                text: () => Promise.resolve(JSON.stringify({ real: true })),
                dump: () => Promise.resolve(),
            })
        )

        const res = await supertest(app)
            .post(`/api/projects/${hogFunction.team_id}/hog_functions/${hogFunction.id}/invocations`)
            .send({ globals, mock_async_functions: false })

        expect(res.status).toEqual(200)
        expect(res.body).toMatchObject({
            errors: [],
            request_origins: ['https://example.com'],
            logs: [
                {
                    level: 'info',
                    message: 'Fetch response:, {"status":201,"body":{"real":true}}',
                },
                {
                    level: 'debug',
                    message: expect.stringContaining('Function completed in'),
                },
            ],
        })
    })

    it('function will return skipped if no invocations', async () => {
        mockFetch.mockImplementationOnce(() =>
            Promise.resolve({
                status: 201,
                headers: { 'Content-Type': 'application/json' },
                json: () => Promise.resolve({ real: true }),
                text: () => Promise.resolve(JSON.stringify({ real: true })),
                dump: () => Promise.resolve(),
            })
        )

        hogFunction = await insertHogFunction({
            name: 'test hog function',
            ...HOG_EXAMPLES.simple_fetch,
            ...HOG_INPUTS_EXAMPLES.simple_fetch,
            ...HOG_FILTERS_EXAMPLES.elements_text_filter,
        })

        const res = await supertest(app)
            .post(`/api/projects/${hogFunction.team_id}/hog_functions/${hogFunction.id}/invocations`)
            .send({ globals, mock_async_functions: false })

        expect(res.status).toEqual(200)

        expect(res.body.status).toMatchInlineSnapshot(`"skipped"`)

        expect(res.body).toMatchObject({
            errors: [],
            logs: [
                {
                    level: 'info',
                    message: 'Mapping trigger not matching filters was ignored.',
                },
            ],
        })
    })

    it('can invoke a function with multiple fetches', async () => {
        mockFetch.mockImplementation(() =>
            Promise.resolve({
                status: 201,
                headers: { 'Content-Type': 'application/json' },
                json: () => Promise.resolve({ real: true }),
                text: () => Promise.resolve(JSON.stringify({ real: true })),
                dump: () => Promise.resolve(),
            })
        )
        const res = await supertest(app)
            .post(
                `/api/projects/${hogFunctionMultiFetch.team_id}/hog_functions/${hogFunctionMultiFetch.id}/invocations`
            )
            .send({ globals, mock_async_functions: false })

        expect(res.body.errors).toMatchInlineSnapshot(`
            [
              "Exceeded maximum number of async steps: 5",
            ]
        `)

        expect(mockFetch).toHaveBeenCalledTimes(5)
        expect(res.body).toMatchObject({
            logs: [
                {
                    level: 'error',
                    message: expect.stringContaining('Error executing function'),
                },
            ],
        })
    })

    it('includes enriched values in the request', async () => {
        mockFetch.mockImplementationOnce(() => {
            return Promise.resolve({
                status: 201,
                headers: { 'Content-Type': 'application/json' },
                json: () => Promise.resolve({ real: true }),
                text: () => Promise.resolve(JSON.stringify({ real: true })),
                dump: () => Promise.resolve(),
            })
        })

        hogFunction = await insertHogFunction({
            ...HOG_EXAMPLES.simple_fetch,
            ...HOG_INPUTS_EXAMPLES.simple_google_fetch,
            ...HOG_FILTERS_EXAMPLES.no_filters,
        })

        const res = await supertest(app)
            .post(`/api/projects/${hogFunction.team_id}/hog_functions/${hogFunction.id}/invocations`)
            .send({ globals, mock_async_functions: false })

        expect(mockFetch).toHaveBeenCalledWith(
            'https://googleads.googleapis.com/',
            expect.objectContaining({
                headers: expect.objectContaining({
                    'developer-token': 'ADWORDS_TOKEN',
                }),
            })
        )

        expect(res.status).toEqual(200)
        expect(res.body).toMatchObject({
            logs: [
                {
                    level: 'info',
                    message: 'Fetch response:, {"status":201,"body":{"real":true}}',
                },
                {
                    level: 'debug',
                    message: expect.stringContaining('Function completed in'),
                },
            ],
        })
    })

    it('doesnt include enriched values in the mock response', async () => {
        hogFunction = await insertHogFunction({
            ...HOG_EXAMPLES.simple_fetch,
            ...HOG_INPUTS_EXAMPLES.simple_google_fetch,
            ...HOG_FILTERS_EXAMPLES.no_filters,
        })

        const res = await supertest(app)
            .post(`/api/projects/${hogFunction.team_id}/hog_functions/${hogFunction.id}/invocations`)
            .send({ globals, mock_async_functions: true })

        expect(res.status).toEqual(200)
        expect(res.body).toMatchObject({
            logs: [
                {
                    level: 'info',
                    message: "Async function 'fetch' was mocked with arguments:",
                },
                {
                    level: 'info',
                    message: expect.not.stringContaining('developer-token'),
                },
                {
                    level: 'info',
                    message: 'Fetch response:, {"status":200,"body":{}}',
                },
                {
                    level: 'debug',
                    message: expect.stringContaining('Function completed in '),
                },
            ],
        })
    })

    it('handles mappings', async () => {
        const hogFunction = await insertHogFunction({
            ...HOG_EXAMPLES.simple_fetch,
            ...HOG_INPUTS_EXAMPLES.simple_fetch,
            ...HOG_FILTERS_EXAMPLES.no_filters,
            mappings: [
                {
                    // Filters for pageview or autocapture
                    ...HOG_FILTERS_EXAMPLES.pageview_or_autocapture_filter,
                },
                {
                    // No filters so should match all events
                    ...HOG_FILTERS_EXAMPLES.no_filters,
                },
                {
                    // Broken filters so shouldn't match
                    ...HOG_FILTERS_EXAMPLES.broken_filters,
                },
            ],
        })

        const res = await supertest(app)
            .post(`/api/projects/${hogFunction.team_id}/hog_functions/${hogFunction.id}/invocations`)
            .send({ globals, mock_async_functions: true })

        expect(res.status).toEqual(200)

        const minimalLogs = res.body.logs.map((log: any) => ({
            level: log.level,
            message: log.message,
        }))

        expect(res.body.status).toMatchInlineSnapshot(`"success"`)

        expect(minimalLogs).toMatchObject([
            { level: 'info', message: 'Mapping trigger not matching filters was ignored.' },
            {
                level: 'error',
                message:
                    'Error filtering event b3a1fe86-b10c-43cc-acaf-d208977608d0: Invalid HogQL bytecode, stack is empty, can not pop',
            },
            {
                level: 'info',
                message: "Async function 'fetch' was mocked with arguments:",
            },
            {
                level: 'info',
                message: expect.stringContaining("fetch('"),
            },
            {
                level: 'info',
                message: 'Fetch response:, {"status":200,"body":{}}',
            },
            {
                level: 'debug',
                message: expect.stringContaining('Function completed in '),
            },
        ])
    })

    it('doesnt include enriched values in the mock response', async () => {
        hogFunction = await insertHogFunction({
            ...HOG_EXAMPLES.simple_fetch,
            ...HOG_INPUTS_EXAMPLES.simple_google_fetch,
            ...HOG_FILTERS_EXAMPLES.no_filters,
        })

        const res = await supertest(app)
            .post(`/api/projects/${hogFunction.team_id}/hog_functions/${hogFunction.id}/invocations`)
            .send({ globals, mock_async_functions: true })

        expect(res.status).toEqual(200)

        expect(res.body.status).toMatchInlineSnapshot(`"success"`)

        expect(res.body.logs.map((log: any) => log.message).slice(0, -1)).toMatchInlineSnapshot(`
            [
              "Async function 'fetch' was mocked with arguments:",
              "fetch('https://googleads.googleapis.com/', {
              "headers": {
                "version": "v=1.0.0"
              },
              "body": {
                "event": {
                  "uuid": "b3a1fe86-b10c-43cc-acaf-d208977608d0",
                  "event": "$pageview",
                  "elements_chain": "",
                  "distinct_id": "123",
                  "timestamp": "2021-09-28T14:00:00Z",
                  "url": "https://example.com/events/b3a1fe86-b10c-43cc-acaf-d208977608d0/2021-09-28T14:00:00Z",
                  "properties": {
                    "$lib_version": "1.0.0"
                  }
                },
                "groups": {},
                "nested": {
                  "foo": "https://example.com/events/b3a1fe86-b10c-43cc-acaf-d208977608d0/2021-09-28T14:00:00Z"
                },
                "person": {
                  "id": "123",
                  "name": "Jane Doe",
                  "url": "https://example.com/person/123",
                  "properties": {
                    "email": "example@posthog.com"
                  }
                },
                "event_url": "https://example.com/events/b3a1fe86-b10c-43cc-acaf-d208977608d0/2021-09-28T14:00:00Z-test"
              },
              "method": "POST"
            })",
              "Fetch response:, {"status":200,"body":{}}",
            ]
        `)
    })

    it('redacts secret input values in mocked async function logs', async () => {
        const SECRET_TOKEN = 'super-secret-bearer-token-xyz'

        const hogFunctionWithSecret = await insertHogFunction({
            name: 'test hog function with secret in headers',
            ...HOG_EXAMPLES.simple_fetch,
            ...HOG_FILTERS_EXAMPLES.no_filters,
            inputs_schema: [
                { key: 'url', type: 'string', label: 'URL', secret: false, required: true },
                { key: 'access_token', type: 'string', label: 'Access token', secret: true, required: true },
                {
                    key: 'method',
                    type: 'choice',
                    label: 'HTTP Method',
                    secret: false,
                    choices: [
                        { label: 'POST', value: 'POST' },
                        { label: 'GET', value: 'GET' },
                    ],
                    required: true,
                },
                { key: 'headers', type: 'dictionary', label: 'Headers', secret: false, required: false },
                { key: 'body', type: 'json', label: 'Body', secret: false, required: true },
            ],
            inputs: {
                url: { value: 'https://example.com/posthog-webhook' },
                access_token: { value: SECRET_TOKEN },
                method: { value: 'POST' },
                headers: { value: { Authorization: `Bearer ${SECRET_TOKEN}` } },
                body: { value: {} },
            },
        })

        const res = await supertest(app)
            .post(
                `/api/projects/${hogFunctionWithSecret.team_id}/hog_functions/${hogFunctionWithSecret.id}/invocations`
            )
            .send({ globals, mock_async_functions: true })

        expect(res.status).toEqual(200)
        expect(res.body.errors).toEqual([])

        const allLogText = res.body.logs.map((log: any) => log.message).join('\n')
        expect(allLogText).not.toContain(SECRET_TOKEN)
        // Confirm the sanitization path actually ran rather than the test passing by virtue of
        // no fetch log being emitted at all.
        expect(allLogText).toContain('***REDACTED***')
    })

    it('returns every claim of a workflow email preferences token', async () => {
        const token = api['recipientTokensService'].generatePreferencesToken(
            { team_id: team.id, identifier: 'recipient@example.com' },
            {
                appSourceId: 'flow-1',
                instanceId: 'action-1',
                workflowId: 'flow-1',
                invocationId: 'run-1',
                workflowVersion: 3,
            }
        )

        const res = await supertest(app).get(`/api/messaging/validate_preferences_token/${token}`)

        expect(res.status).toEqual(200)
        expect(res.body).toEqual({
            valid: true,
            team_id: team.id,
            identifier: 'recipient@example.com',
            app_source_id: 'flow-1',
            instance_id: 'action-1',
            workflow_id: 'flow-1',
            invocation_id: 'run-1',
            workflow_version: 3,
        })
    })

    describe('transformations', () => {
        let configuration: HogFunctionType

        beforeEach(() => {
            configuration = createHogFunction({
                type: 'transformation',
                name: posthogFilterOutPlugin.template.name,
                template_id: 'plugin-posthog-filter-out-plugin',
                inputs: {
                    eventsToDrop: {
                        value: 'drop me',
                    },
                },
                team_id: team.id,
                enabled: true,
                hog: posthogFilterOutPlugin.template.code,
                inputs_schema: posthogFilterOutPlugin.template.inputs_schema,
            })
        })

        it('processes transformations and returns the result if not null', async () => {
            const res = await supertest(app)
                .post(`/api/projects/${hogFunction.team_id}/hog_functions/new/invocations`)
                .send({ globals, mock_async_functions: true, configuration })

            expect(res.status).toEqual(200)

            expect(res.body.logs.map((log: any) => log.message)).toMatchInlineSnapshot(`[]`)

            expect(forSnapshot(res.body.result)).toMatchInlineSnapshot(`
                {
                  "distinct_id": "123",
                  "elements_chain": "",
                  "event": "$pageview",
                  "ip": null,
                  "now": "",
                  "properties": {
                    "$lib_version": "1.0.0",
                  },
                  "site_url": "http://localhost:8000/project/2",
                  "team_id": 2,
                  "timestamp": "2021-09-28T14:00:00Z",
                  "url": "https://example.com/events/<REPLACED-UUID-0>/2021-09-28T14:00:00Z",
                  "uuid": "<REPLACED-UUID-0>",
                }
            `)
        })

        it('processes transformations and returns the result if null', async () => {
            globals.event!.event = 'drop me'

            const res = await supertest(app)
                .post(`/api/projects/${hogFunction.team_id}/hog_functions/new/invocations`)
                .send({ globals, mock_async_functions: true, configuration })

            expect(res.status).toEqual(200)
            expect(res.body.logs.map((log: any) => log.message)).toMatchInlineSnapshot(`[]`)
            expect(res.body.result).toMatchInlineSnapshot(`null`)
        })
    })

    describe('log transformations', () => {
        let configuration: HogFunctionType

        const logRecordGlobals = {
            record: {
                body: 'login ok password=hunter2',
                severity_text: 'info',
                severity_number: 9,
                service_name: 'payments-api',
                attributes: { 'http.method': 'POST' },
                resource_attributes: { 'k8s.namespace.name': 'payments' },
            },
        }

        beforeEach(async () => {
            const hog = `
                let r := record
                if (r.severity_text == 'debug') {
                    return null
                }
                if (r.body != null) {
                    r.body := replaceAll(r.body, inputs.needle, '[REDACTED]')
                }
                r.attributes.transformed := 'true'
                return r
            `
            configuration = createHogFunction({
                type: 'transformation_log',
                name: 'Test log transformation',
                team_id: team.id,
                enabled: true,
                hog,
                bytecode: await compileHog(hog),
                inputs: { needle: { value: 'hunter2' } },
            })
        })

        it('transforms a mock log record', async () => {
            const res = await supertest(app)
                .post(`/api/projects/${team.id}/hog_functions/new/invocations`)
                .send({ globals: logRecordGlobals, configuration })

            expect(res.status).toEqual(200)
            expect(res.body.status).toEqual('success')
            expect(res.body.errors).toEqual([])
            expect(res.body.result.body).toEqual('login ok password=[REDACTED]')
            expect(res.body.result.severity_text).toEqual('info')
            expect(res.body.result.attributes).toEqual({ 'http.method': 'POST', transformed: 'true' })
        })

        it('returns null result when the record is dropped', async () => {
            const res = await supertest(app)
                .post(`/api/projects/${team.id}/hog_functions/new/invocations`)
                .send({
                    globals: { record: { ...logRecordGlobals.record, severity_text: 'debug' } },
                    configuration,
                })

            expect(res.status).toEqual(200)
            expect(res.body.status).toEqual('success')
            expect(res.body.result).toEqual(null)
            expect(res.body.logs.map((log: any) => log.message)).toContain('Record dropped by transformation.')
        })

        it('returns 400 when the record global is missing', async () => {
            const res = await supertest(app)
                .post(`/api/projects/${team.id}/hog_functions/new/invocations`)
                .send({ globals: {}, configuration })

            expect(res.status).toEqual(400)
            expect(res.body.error).toEqual('Missing record')
        })

        it('reports a malformed return value as an error', async () => {
            // Returning a non-record, non-null value is a customer mistake the endpoint must surface
            const hog = `return 42`
            const res = await supertest(app)
                .post(`/api/projects/${team.id}/hog_functions/new/invocations`)
                .send({
                    globals: logRecordGlobals,
                    configuration: { ...configuration, hog, bytecode: await compileHog(hog) },
                })

            expect(res.status).toEqual(200)
            expect(res.body.status).toEqual('error')
            expect(res.body.errors.length).toBeGreaterThan(0)
        })

        it('captures print output from the transformation', async () => {
            const hog = `
                print('inspecting', record.service_name)
                return record
            `
            const res = await supertest(app)
                .post(`/api/projects/${team.id}/hog_functions/new/invocations`)
                .send({
                    globals: logRecordGlobals,
                    configuration: { ...configuration, hog, bytecode: await compileHog(hog) },
                })

            expect(res.status).toEqual(200)
            expect(res.body.status).toEqual('success')
            expect(res.body.logs.map((log: any) => log.message)).toContain('inspecting, payments-api')
        })
    })

    describe('hog function states', () => {
        beforeEach(async () => {
            jest.spyOn(hub.teamManager, 'getTeam').mockResolvedValue(team)
            const redis = createRedisV2PoolFromConfig({
                connection: hub.CDP_REDIS_HOST
                    ? {
                          url: hub.CDP_REDIS_HOST,
                          options: { port: hub.CDP_REDIS_PORT, password: hub.CDP_REDIS_PASSWORD },
                      }
                    : { url: hub.REDIS_URL },
                poolMinSize: hub.REDIS_POOL_MIN_SIZE,
                poolMaxSize: hub.REDIS_POOL_MAX_SIZE,
            })
            await deleteKeysWithPrefix(redis, BASE_REDIS_KEY)
        })

        afterAll(() => {
            jest.restoreAllMocks()
        })

        it('returns the states of all hog functions', async () => {
            await api['hogWatcher'].forceStateChange(hogFunction, HogWatcherState.degraded)
            await api['hogWatcher'].forceStateChange(hogFunctionMultiFetch, HogWatcherState.disabled)

            const res = await supertest(app).get('/api/hog_functions/states')
            expect(res.status).toEqual(200)
            expect(res.body).toEqual({
                results: [
                    {
                        function_enabled: true,
                        function_id: hogFunctionMultiFetch.id,
                        function_name: 'test hog function multi fetch',
                        function_team_id: hogFunctionMultiFetch.team_id,
                        function_type: 'destination',
                        state: 'disabled',
                        state_numeric: 3,
                        tokens: 10000,
                    },
                    {
                        function_enabled: true,
                        function_id: hogFunction.id,
                        function_name: 'test hog function',
                        function_team_id: hogFunction.team_id,
                        function_type: 'destination',
                        state: 'degraded',
                        state_numeric: 2,
                        tokens: 10000,
                    },
                ],
                total: 2,
            })
        })
    })

    describe('body size limits', () => {
        const largePayload = 'x'.repeat(600 * 1024)

        it('accepts large payloads on hog function invocations endpoint', async () => {
            const res = await supertest(app)
                .post(`/api/projects/${hogFunction.team_id}/hog_functions/${hogFunction.id}/invocations`)
                .send({ globals, mock_async_functions: true, configuration: { large_field: largePayload } })

            expect(res.status).toEqual(200)
        })

        it('accepts large payloads on hog flow invocations endpoint', async () => {
            const res = await supertest(app)
                .post(`/api/projects/${hogFunction.team_id}/hog_flows/new/invocations`)
                .send({ globals, mock_async_functions: true, configuration: { large_field: largePayload } })

            // 400 from missing flow config, not 413/500 from body size
            expect(res.status).not.toEqual(413)
            expect(res.status).not.toEqual(500)
        })

        it('rejects large payloads on public webhooks endpoint', async () => {
            const res = await supertest(app).post('/public/webhooks/test-webhook').send({ large_field: largePayload })

            expect(res.status).toEqual(413)
            expect(res.body).toEqual({ error: 'Request entity too large' })
        })
    })

    describe('hogflow invocation groups', () => {
        const resolvedGroup = {
            id: 'org-1',
            type: 'organization',
            index: 0,
            url: 'http://localhost:8000/groups/0/org-1',
            properties: { plan: 'enterprise' },
        }

        const groupGlobals: Partial<HogFunctionInvocationGlobals> = {
            ...globals,
            groups: {},
            event: {
                ...globals.event!,
                properties: { $groups: { organization: 'org-1' } },
            },
        }

        let executeSpy: jest.SpyInstance
        let getGroupsSpy: jest.SpyInstance

        beforeEach(() => {
            executeSpy = jest.spyOn(api['hogFlowExecutor'], 'executeCurrentAction').mockImplementation(((
                invocation: any
            ) =>
                Promise.resolve({
                    invocation,
                    error: null,
                    logs: [],
                    execResult: null,
                })) as any)
            getGroupsSpy = jest
                .spyOn(api['groupsManager'], 'getGroupsForEvent')
                .mockResolvedValue({ organization: resolvedGroup })
        })

        afterEach(() => {
            executeSpy.mockRestore()
            getGroupsSpy.mockRestore()
        })

        it('resolves groups from the event when none are provided', async () => {
            const res = await supertest(app)
                .post(`/api/projects/${team.id}/hog_flows/new/invocations`)
                .send({ globals: groupGlobals, mock_async_functions: true, configuration: {} })

            expect(res.status).toEqual(200)
            expect(getGroupsSpy).toHaveBeenCalledWith(
                team.id,
                expect.objectContaining({ $groups: { organization: 'org-1' } }),
                expect.stringContaining(`/project/${team.id}`)
            )
            // Resolved groups flow into filterGlobals so conditional branches can evaluate them
            const invocation = executeSpy.mock.calls[0][0]
            expect(invocation.filterGlobals.group_0).toEqual({ properties: { plan: 'enterprise' } })
            expect(invocation.filterGlobals.$group_0).toEqual('org-1')
        })

        it('does not override groups provided in the payload', async () => {
            const providedGroups = {
                organization: { ...resolvedGroup, id: 'org-provided', properties: { plan: 'startup' } },
            }
            const res = await supertest(app)
                .post(`/api/projects/${team.id}/hog_flows/new/invocations`)
                .send({
                    globals: { ...groupGlobals, groups: providedGroups },
                    mock_async_functions: true,
                    configuration: {},
                })

            expect(res.status).toEqual(200)
            expect(getGroupsSpy).not.toHaveBeenCalled()
            const invocation = executeSpy.mock.calls[0][0]
            expect(invocation.filterGlobals.$group_0).toEqual('org-provided')
        })
    })

    describe('hogflow trigger test invocations', () => {
        const accountPropertyChangedFlowConfiguration = {
            id: 'account-property-changed-flow',
            team_id: 0,
            name: 'Account property changed flow',
            actions: [
                {
                    id: 'trigger_node',
                    name: 'Trigger',
                    type: 'trigger',
                    config: {
                        type: 'event',
                        filters: {
                            events: [
                                {
                                    id: '$account_custom_property_changed',
                                    name: 'Account custom property changed',
                                    type: 'events',
                                    order: 0,
                                    properties: [
                                        { key: 'property_name', value: 'Plan', operator: 'exact', type: 'event' },
                                        { key: 'current_value', value: 'enterprise', operator: 'exact', type: 'event' },
                                    ],
                                },
                            ],
                            properties: [],
                            // properties.current_value == 'enterprise' AND properties.property_name == 'Plan'
                            bytecode: [
                                '_H',
                                1,
                                32,
                                'enterprise',
                                32,
                                'current_value',
                                32,
                                'properties',
                                1,
                                2,
                                11,
                                32,
                                'Plan',
                                32,
                                'property_name',
                                32,
                                'properties',
                                1,
                                2,
                                11,
                                3,
                                2,
                            ],
                        },
                    },
                },
                { id: 'exit_node', name: 'Exit', type: 'exit', config: {} },
            ],
            edges: [{ from: 'trigger_node', to: 'exit_node', type: 'continue' }],
        }

        it.each([
            ['matching', 'enterprise', 'success', 'exit_node'],
            ['non-matching', 'free', 'skipped', null],
        ])(
            'reports a %s current_value filter result',
            async (_, currentValue, expectedStatus, expectedNextActionId) => {
                const res = await supertest(app)
                    .post(`/api/projects/${team.id}/hog_flows/new/invocations`)
                    .send({
                        globals: {
                            ...globals,
                            event: {
                                ...globals.event!,
                                event: '$account_custom_property_changed',
                                properties: {
                                    ...globals.event!.properties,
                                    property_name: 'Plan',
                                    current_value: currentValue,
                                },
                            },
                        },
                        mock_async_functions: true,
                        configuration: { ...accountPropertyChangedFlowConfiguration, team_id: team.id },
                    })

                expect(res.status).toEqual(200)
                expect(res.body.status).toEqual(expectedStatus)
                expect(res.body.nextActionId).toEqual(expectedNextActionId)
                if (expectedStatus === 'skipped') {
                    expect(res.body.logs).toEqual(
                        expect.arrayContaining([
                            expect.objectContaining({ message: 'Workflow trigger did not match the event.' }),
                        ])
                    )
                }
            }
        )

        const slackMessageFlowConfiguration = {
            id: 'slack-message-flow',
            team_id: 0,
            name: 'Slack message flow',
            actions: [
                {
                    id: 'trigger_node',
                    name: 'Trigger',
                    type: 'trigger',
                    config: {
                        type: 'internal-event',
                        filters: {
                            source: 'internal-events',
                            events: [{ id: '$slack_message_received', type: 'events' }],
                            properties: [{ key: 'channel', value: 'C0ALERTS', operator: 'exact', type: 'event' }],
                            // properties.channel == 'C0ALERTS'
                            bytecode: ['_H', 1, 32, 'C0ALERTS', 32, 'channel', 32, 'properties', 1, 2, 11],
                        },
                    },
                },
                { id: 'exit_node', name: 'Exit', type: 'exit', config: {} },
            ],
            edges: [{ from: 'trigger_node', to: 'exit_node', type: 'continue' }],
        }

        it.each([
            ['skips a non-slack event', '$pageview', 'skipped', null],
            ['passes a matching slack message', '$slack_message_received', 'success', 'exit_node'],
        ])(
            '%s against a Slack-connected internal-event trigger',
            async (_, eventName, expectedStatus, expectedNextActionId) => {
                const res = await supertest(app)
                    .post(`/api/projects/${team.id}/hog_flows/new/invocations`)
                    .send({
                        globals: {
                            ...globals,
                            event: {
                                ...globals.event!,
                                event: eventName,
                                properties: { channel: 'C0ALERTS', text: 'deploy failed' },
                            },
                        },
                        mock_async_functions: true,
                        configuration: { ...slackMessageFlowConfiguration, team_id: team.id },
                    })

                expect(res.status).toEqual(200)
                expect(res.body.status).toEqual(expectedStatus)
                expect(res.body.nextActionId).toEqual(expectedNextActionId)
                if (expectedStatus === 'skipped') {
                    expect(res.body.logs).toEqual(
                        expect.arrayContaining([
                            expect.objectContaining({
                                message: expect.stringContaining('would not trigger this workflow'),
                            }),
                        ])
                    )
                }
            }
        )
    })

    describe('hogflow wait_until_condition test invocations', () => {
        // Matches events whose name equals `eventName` - same shape the serializer compiles
        // for an "events to wait for" entry.
        const eventBytecode = (eventName: string): any[] => ['_H', 1, 32, eventName, 32, 'event', 1, 1, 11]

        const waitFlowConfiguration = {
            name: 'Wait flow',
            actions: [
                { id: 'trigger_node', name: 'Trigger', type: 'trigger', config: { type: 'event', filters: {} } },
                {
                    id: 'wait_node',
                    name: 'Wait',
                    type: 'wait_until_condition',
                    config: {
                        events: [
                            {
                                filters: {
                                    bytecode: eventBytecode('follow_up'),
                                    events: [{ id: 'follow_up', name: 'follow_up', type: 'events', order: 0 }],
                                },
                            },
                        ],
                        condition: { filters: null },
                        max_wait_duration: '5m',
                    },
                },
                { id: 'exit_node', name: 'Exit', type: 'exit', config: {} },
            ],
            edges: [
                { from: 'wait_node', to: 'exit_node', type: 'branch', index: 0 },
                { from: 'wait_node', to: 'exit_node', type: 'continue' },
            ],
        }

        it.each([
            ['matching', 'follow_up', 'exit_node'],
            ['non-matching', 'some_other_event', 'wait_node'],
        ])('a %s test event resolves the wait step correctly', async (_, eventName, expectedNextActionId) => {
            const res = await supertest(app)
                .post(`/api/projects/${team.id}/hog_flows/new/invocations`)
                .send({
                    globals: { ...globals, event: { ...globals.event!, event: eventName } },
                    mock_async_functions: true,
                    configuration: waitFlowConfiguration,
                    current_action_id: 'wait_node',
                })

            expect(res.status).toEqual(200)
            expect(res.body.status).toEqual('success')
            expect(res.body.nextActionId).toEqual(expectedNextActionId)
        })
    })

    it('redacts a flow function action secret from mocked async function logs', async () => {
        const SECRET_TOKEN = 'super-secret-flow-token-xyz'

        await insertHogFunctionTemplate(hub.postgres, {
            id: 'template-cdp-api-flow-secret-fetch',
            name: 'Flow secret fetch',
            code: `fetch(inputs.url, { 'method': 'POST', 'headers': { 'Authorization': f'Bearer {inputs.access_token}' } })`,
            inputs_schema: [
                { key: 'url', type: 'string', label: 'URL', secret: false, required: true },
                { key: 'access_token', type: 'string', label: 'Access token', secret: true, required: true },
            ],
        })

        const flowConfiguration = {
            name: 'Flow with secret fetch',
            actions: [
                { id: 'trigger_node', name: 'Trigger', type: 'trigger', config: { type: 'event', filters: {} } },
                {
                    id: 'fetch_node',
                    name: 'Fetch',
                    type: 'function',
                    config: {
                        template_id: 'template-cdp-api-flow-secret-fetch',
                        inputs: {
                            url: { value: 'https://example.com/hook' },
                            access_token: { value: SECRET_TOKEN },
                        },
                    },
                },
                { id: 'exit_node', name: 'Exit', type: 'exit', config: {} },
            ],
            edges: [
                { from: 'trigger_node', to: 'fetch_node', type: 'continue' },
                { from: 'fetch_node', to: 'exit_node', type: 'continue' },
            ],
        }

        const res = await supertest(app).post(`/api/projects/${team.id}/hog_flows/new/invocations`).send({
            globals,
            mock_async_functions: true,
            configuration: flowConfiguration,
            current_action_id: 'fetch_node',
        })

        expect(res.status).toEqual(200)
        const allLogText = res.body.logs.map((log: any) => log.message).join('\n')
        expect(allLogText).not.toContain(SECRET_TOKEN)
        // Confirm redaction actually ran, rather than passing because no fetch log was emitted.
        expect(allLogText).toContain('***REDACTED***')
    })

    it.each([
        ['real', false, ['https://example.com']],
        ['mocked', true, []],
    ])('reports the origins a flow step with %s requests sent to', async (_, mockAsyncFunctions, expectedOrigins) => {
        mockFetch.mockImplementation(() =>
            Promise.resolve({
                status: 200,
                headers: { 'Content-Type': 'application/json' },
                json: () => Promise.resolve({}),
                text: () => Promise.resolve('{}'),
                dump: () => Promise.resolve(),
            })
        )
        await insertHogFunctionTemplate(hub.postgres, {
            id: 'template-cdp-api-flow-origin-fetch',
            name: 'Flow origin fetch',
            code: `fetch(inputs.url, { 'method': 'POST' })`,
            inputs_schema: [{ key: 'url', type: 'string', label: 'URL', secret: false, required: true }],
        })

        const res = await supertest(app)
            .post(`/api/projects/${team.id}/hog_flows/new/invocations`)
            .send({
                globals,
                mock_async_functions: mockAsyncFunctions,
                current_action_id: 'fetch_node',
                configuration: {
                    name: 'Flow with a fetch',
                    actions: [
                        {
                            id: 'trigger_node',
                            name: 'Trigger',
                            type: 'trigger',
                            config: { type: 'event', filters: {} },
                        },
                        {
                            id: 'fetch_node',
                            name: 'Fetch',
                            type: 'function',
                            config: {
                                template_id: 'template-cdp-api-flow-origin-fetch',
                                inputs: { url: { value: 'https://user:password@example.com/hook?token=abc' } },
                            },
                        },
                        { id: 'exit_node', name: 'Exit', type: 'exit', config: {} },
                    ],
                    edges: [
                        { from: 'trigger_node', to: 'fetch_node', type: 'continue' },
                        { from: 'fetch_node', to: 'exit_node', type: 'continue' },
                    ],
                },
            })

        expect(res.status).toEqual(200)
        expect(res.body).toMatchObject({ errors: [], request_origins: expectedOrigins })
    })

    describe('batch hogflow invocations', () => {
        let batchHogFlow: HogFlow

        beforeEach(async () => {
            batchHogFlow = await insertHogFlow({
                id: new UUIDT().toString(),
                name: 'test batch hog flow',
                status: 'active',
                version: 1,
                exit_condition: 'exit_on_conversion',
                edges: [],
                actions: [],
                trigger: {
                    type: 'batch',
                    filters: {
                        properties: [
                            {
                                key: 'email',
                                value: 'test@posthog.com',
                                operator: 'exact',
                                type: 'person',
                            },
                        ],
                    },
                },
            })
        })

        it('errors if missing team', async () => {
            const nonExistentTeamId = new UUIDT().toString()
            const res = await supertest(app)
                .post(`/api/projects/${nonExistentTeamId}/hog_flows/${batchHogFlow.id}/batch_invocations/job-123`)
                .send({})

            expect(res.status).toEqual(404)
            expect(res.body.error).toEqual('Team not found')
        })

        it('errors if missing hog flow', async () => {
            const nonExistentUuid = new UUIDT().toString()
            const res = await supertest(app)
                .post(`/api/projects/${batchHogFlow.team_id}/hog_flows/${nonExistentUuid}/batch_invocations/job-123`)
                .send({})

            expect(res.status).toEqual(404)
            expect(res.body.error).toEqual('Workflow not found')
        })

        it('errors if hog flow is not a batch trigger type', async () => {
            const nonBatchHogFlow = await insertHogFlow({
                id: new UUIDT().toString(),
                name: 'test non-batch hog flow',
                status: 'active',
                version: 1,
                exit_condition: 'exit_on_conversion',
                edges: [],
                actions: [],
                trigger: {
                    type: 'event',
                    filters: {},
                },
            })

            const res = await supertest(app)
                .post(
                    `/api/projects/${nonBatchHogFlow.team_id}/hog_flows/${nonBatchHogFlow.id}/batch_invocations/job-123`
                )
                .send({})

            expect(res.status).toEqual(400)
            expect(res.body.error).toEqual('Only batch Workflows are supported for batch jobs')
        })

        it('queues batch job to the cyclotron resolver', async () => {
            const createJobMock = jest.fn().mockResolvedValue('resolver-job-id')
            api['batchResolverProducer'] = fakeJobProducer({
                createJob: createJobMock,
                countInFlightJobs: jest.fn().mockResolvedValue({ count: 0, byAction: {}, positionUnknown: 0 }),
            })

            try {
                const res = await supertest(app)
                    .post(
                        `/api/projects/${batchHogFlow.team_id}/hog_flows/${batchHogFlow.id}/batch_invocations/job-789`
                    )
                    .send({
                        filters: { filter_test_accounts: true },
                        max_audience_size: 1234,
                        variables: { foo: 'bar' },
                    })

                expect(res.status).toEqual(200)
                expect(res.body).toEqual({ status: 'queued' })

                expect(createJobMock).toHaveBeenCalledTimes(1)
                const arg = createJobMock.mock.calls[0][0]
                expect(arg).toMatchObject({
                    teamId: batchHogFlow.team_id,
                    queueName: 'hogflow_batch_resolve',
                    parentRunId: 'job-789',
                    functionId: batchHogFlow.id,
                })
                expect(arg.state).toBeInstanceOf(Buffer)
                const state = parseJSON((arg.state as Buffer).toString('utf-8')) as Record<string, unknown>
                expect(state).toMatchObject({
                    batchJobId: 'job-789',
                    teamId: batchHogFlow.team_id,
                    hogFlowId: batchHogFlow.id,
                    filters: {
                        properties: (batchHogFlow as any).trigger.filters.properties,
                        filter_test_accounts: true,
                    },
                    maxAudienceSize: 1234,
                    variables: { foo: 'bar' },
                    cursor: null,
                    totalEnqueued: 0,
                    pagesProcessed: 0,
                })
                // No email action in the flow, so the audience must not be deduped by email
                expect(state.dedupeKey).toBeUndefined()
            } finally {
                api['batchResolverProducer'] = null
            }
        })

        it.each([
            ['a deadline', { id: 7, team_id: 1, wait_until: '2026-10-17T10:00:00Z' }, 200, '2026-10-17T10:00:00.000Z'],
            ['no deadline', { id: 7, team_id: 1 }, 200, undefined],
            ['an unreadable deadline', { id: 7, team_id: 1, wait_until: 'tomorrow-ish' }, 400, undefined],
            ['a non-string deadline', { id: 7, team_id: 1, wait_until: 1234 }, 400, undefined],
        ])(
            'parks a realtime cohort resolver only on a valid deadline: %s',
            async (_desc, cohort, status, parkedUntil) => {
                const createJobMock = jest.fn().mockResolvedValue('resolver-job-id')
                api['batchResolverProducer'] = fakeJobProducer({ createJob: createJobMock })

                try {
                    const res = await supertest(app)
                        .post(
                            `/api/projects/${batchHogFlow.team_id}/hog_flows/${batchHogFlow.id}/batch_invocations/job-793`
                        )
                        .send({ realtime_cohort: cohort })

                    expect(res.status).toEqual(status)
                    if (status !== 200) {
                        expect(createJobMock).not.toHaveBeenCalled()
                        return
                    }
                    const arg = createJobMock.mock.calls[0][0]
                    expect(arg.scheduled?.toISOString()).toEqual(parkedUntil)
                    const state = parseJSON((arg.state as Buffer).toString('utf-8')) as Record<string, any>
                    expect(state.realtimeCohort).toEqual({
                        id: 7,
                        teamId: 1,
                        ...(parkedUntil ? { waitUntil: parkedUntil } : {}),
                    })
                } finally {
                    api['batchResolverProducer'] = null
                }
            }
        )

        it('resolves the audience from the posted snapshot, not the live trigger filters', async () => {
            // The snapshot was validated at confirm time - re-reading the trigger here would let an
            // edit racing the dispatch widen the send past what was previewed.
            const snapshotProperties = [{ key: 'email', type: 'person', value: 'a', operator: 'icontains' }]

            const createJobMock = jest.fn().mockResolvedValue('resolver-job-id')
            api['batchResolverProducer'] = fakeJobProducer({
                createJob: createJobMock,
                countInFlightJobs: jest.fn().mockResolvedValue({ count: 0, byAction: {}, positionUnknown: 0 }),
            })

            try {
                const res = await supertest(app)
                    .post(
                        `/api/projects/${batchHogFlow.team_id}/hog_flows/${batchHogFlow.id}/batch_invocations/job-791`
                    )
                    .send({ filters: { properties: snapshotProperties, assignment_status: 'assigned' } })

                expect(res.status).toEqual(200)
                const arg = createJobMock.mock.calls[0][0]
                const state = parseJSON((arg.state as Buffer).toString('utf-8')) as Record<string, any>
                expect(state.filters.properties).toEqual(snapshotProperties)
                expect(state.filters.assignment_status).toEqual('assigned')
                expect(state.filters.all_roles_unassigned).toBeUndefined()
                expect(state.filters.properties).not.toEqual((batchHogFlow as any).trigger.filters.properties)
            } finally {
                api['batchResolverProducer'] = null
            }
        })

        it('takes the whole assignment filter from the snapshot instead of one key at a time', async () => {
            // A snapshot saved before assignment statuses existed carries assignee ids and no status.
            // If the status came off the live trigger instead, Django would reject 'unassigned'
            // paired with those ids and the run would fail.
            const statusFlow = await insertHogFlow({
                id: new UUIDT().toString(),
                name: 'test batch hog flow with an assignment status',
                status: 'active',
                version: 1,
                exit_condition: 'exit_on_conversion',
                edges: [],
                actions: [],
                trigger: {
                    type: 'batch',
                    filters: {
                        audience_type: 'accounts',
                        properties: [],
                        assignment_status: 'unassigned',
                        assigned_to_user_ids: [],
                    },
                },
            })

            const createJobMock = jest.fn().mockResolvedValue('resolver-job-id')
            api['batchResolverProducer'] = fakeJobProducer({
                createJob: createJobMock,
                countInFlightJobs: jest.fn().mockResolvedValue({ count: 0, byAction: {}, positionUnknown: 0 }),
            })

            try {
                const res = await supertest(app)
                    .post(`/api/projects/${statusFlow.team_id}/hog_flows/${statusFlow.id}/batch_invocations/job-792`)
                    .send({ filters: { audience_type: 'accounts', properties: [], assigned_to_user_ids: [7] } })

                expect(res.status).toEqual(200)
                const arg = createJobMock.mock.calls[0][0]
                const state = parseJSON((arg.state as Buffer).toString('utf-8')) as Record<string, any>
                expect(state.filters.assigned_to_user_ids).toEqual([7])
                expect(state.filters.assignment_status).toBeUndefined()
            } finally {
                api['batchResolverProducer'] = null
            }
        })

        it('sets email dedupe on the resolver state when the flow sends email to the default {{person.properties.email}}', async () => {
            const emailHogFlow = await insertHogFlow({
                id: new UUIDT().toString(),
                name: 'test batch email hog flow',
                status: 'active',
                version: 1,
                exit_condition: 'exit_on_conversion',
                edges: [],
                actions: [
                    {
                        id: 'email_1',
                        type: 'function_email',
                        name: 'Send email',
                        config: {
                            template_id: 'template-email',
                            inputs: {
                                email: {
                                    value: {
                                        to: { email: '{{ person.properties.email }}', name: '' },
                                        from: {},
                                        subject: 'Hi',
                                        text: 'Hello',
                                        html: '<p>Hello</p>',
                                    },
                                },
                            },
                        },
                    },
                ] as any,
                trigger: {
                    type: 'batch',
                    filters: { properties: [] },
                },
            })

            const createJobMock = jest.fn().mockResolvedValue('resolver-job-id')
            api['batchResolverProducer'] = fakeJobProducer({
                createJob: createJobMock,
                countInFlightJobs: jest.fn().mockResolvedValue({ count: 0, byAction: {}, positionUnknown: 0 }),
            })

            try {
                const res = await supertest(app)
                    .post(
                        `/api/projects/${emailHogFlow.team_id}/hog_flows/${emailHogFlow.id}/batch_invocations/job-790`
                    )
                    .send({})

                expect(res.status).toEqual(200)
                const arg = createJobMock.mock.calls[0][0]
                const state = parseJSON((arg.state as Buffer).toString('utf-8')) as Record<string, unknown>
                expect(state.dedupeKey).toEqual('email')
            } finally {
                api['batchResolverProducer'] = null
            }
        })

        it('skips email dedupe when the flow sends to a customized recipient (e.g. work_email)', async () => {
            // Regression guard for the wrong-property footgun: if the customer wired their
            // email action to send to `person.properties.work_email`, deduping on
            // `person.properties.email` would collapse the wrong groups. Better to skip dedupe.
            const emailHogFlow = await insertHogFlow({
                id: new UUIDT().toString(),
                name: 'test batch email hog flow (custom recipient)',
                status: 'active',
                version: 1,
                exit_condition: 'exit_on_conversion',
                edges: [],
                actions: [
                    {
                        id: 'email_1',
                        type: 'function_email',
                        name: 'Send email',
                        config: {
                            template_id: 'template-email',
                            inputs: {
                                email: {
                                    value: {
                                        to: { email: '{{ person.properties.work_email }}', name: '' },
                                        from: {},
                                        subject: 'Hi',
                                        text: 'Hello',
                                        html: '<p>Hello</p>',
                                    },
                                },
                            },
                        },
                    },
                ] as any,
                trigger: {
                    type: 'batch',
                    filters: { properties: [] },
                },
            })

            const createJobMock = jest.fn().mockResolvedValue('resolver-job-id')
            api['batchResolverProducer'] = fakeJobProducer({
                createJob: createJobMock,
                countInFlightJobs: jest.fn().mockResolvedValue({ count: 0, byAction: {}, positionUnknown: 0 }),
            })

            try {
                const res = await supertest(app)
                    .post(
                        `/api/projects/${emailHogFlow.team_id}/hog_flows/${emailHogFlow.id}/batch_invocations/job-791`
                    )
                    .send({})

                expect(res.status).toEqual(200)
                const arg = createJobMock.mock.calls[0][0]
                const state = parseJSON((arg.state as Buffer).toString('utf-8')) as Record<string, unknown>
                expect(state.dedupeKey).toBeUndefined()
            } finally {
                api['batchResolverProducer'] = null
            }
        })
    })

    describe('scheduled hogflow invocations', () => {
        let scheduleHogFlow: HogFlow
        let mockQueueInvocations: jest.Mock

        beforeEach(async () => {
            mockQueueInvocations = jest.fn().mockResolvedValue(undefined)
            api['hogflowQueue'] = { queueInvocations: mockQueueInvocations } as any

            scheduleHogFlow = await insertHogFlow({
                id: new UUIDT().toString(),
                name: 'test schedule hog flow',
                status: 'active',
                version: 1,
                exit_condition: 'exit_only_at_end',
                edges: [],
                actions: [],
                trigger: {
                    type: 'schedule',
                },
            })
        })

        it('errors if missing team', async () => {
            const nonExistentTeamId = new UUIDT().toString()
            const res = await supertest(app)
                .post(`/api/projects/${nonExistentTeamId}/hog_flows/${scheduleHogFlow.id}/scheduled_invocations`)
                .send({})

            expect(res.status).toEqual(404)
            expect(res.body.error).toEqual('Team not found')
        })

        it('errors if missing hog flow', async () => {
            const nonExistentUuid = new UUIDT().toString()
            const res = await supertest(app)
                .post(`/api/projects/${scheduleHogFlow.team_id}/hog_flows/${nonExistentUuid}/scheduled_invocations`)
                .send({})

            expect(res.status).toEqual(404)
            expect(res.body.error).toEqual('Workflow not found')
        })

        it('errors if trigger type is not schedule', async () => {
            const eventHogFlow = await insertHogFlow({
                id: new UUIDT().toString(),
                name: 'test event hog flow',
                status: 'active',
                version: 1,
                exit_condition: 'exit_on_conversion',
                edges: [],
                actions: [],
                trigger: {
                    type: 'event',
                    filters: {},
                },
            })

            const res = await supertest(app)
                .post(`/api/projects/${eventHogFlow.team_id}/hog_flows/${eventHogFlow.id}/scheduled_invocations`)
                .send({})

            expect(res.status).toEqual(400)
            expect(res.body.error).toEqual('Workflow trigger must be of type "schedule"')
        })

        it('queues invocation and returns queued status', async () => {
            const res = await supertest(app)
                .post(`/api/projects/${scheduleHogFlow.team_id}/hog_flows/${scheduleHogFlow.id}/scheduled_invocations`)
                .send({ variables: { greeting: 'Hello' } })

            expect(res.status).toEqual(200)
            expect(res.body.status).toEqual('queued')
            expect(res.body.invocation_id).toBeDefined()
            expect(mockQueueInvocations).toHaveBeenCalledTimes(1)
        })

        it('stamps the run start into the state before the invocation is queued', async () => {
            // Snapshot at call time, so a stamp applied after queueInvocations does not count.
            let stateWhenQueued: string | undefined
            mockQueueInvocations.mockImplementation((invocations: any[]) => {
                stateWhenQueued = JSON.stringify(invocations[0].state)
                return Promise.resolve()
            })
            // `hub` is shared across this file, so the flag is restored rather than left on.
            const resultsEnabled = hub.HOG_INVOCATION_RESULTS_ENABLED
            hub.HOG_INVOCATION_RESULTS_ENABLED = true

            try {
                const res = await supertest(app)
                    .post(
                        `/api/projects/${scheduleHogFlow.team_id}/hog_flows/${scheduleHogFlow.id}/scheduled_invocations`
                    )
                    .send({})

                expect(res.status).toEqual(200)
                expect(parseJSON(stateWhenQueued!).firstScheduledAt).toEqual(expect.any(String))
            } finally {
                hub.HOG_INVOCATION_RESULTS_ENABLED = resultsEnabled
            }
        })

        it('drops the buffered lifecycle row when the invocation cannot be queued', async () => {
            const resultsEnabled = hub.HOG_INVOCATION_RESULTS_ENABLED
            hub.HOG_INVOCATION_RESULTS_ENABLED = true
            const rowsService = api['invocationResultsService'].invocationResultsRowsService
            const produceSpy = jest.spyOn(rowsService['outputs'], 'produce').mockResolvedValue(undefined as any)
            mockQueueInvocations.mockRejectedValueOnce(new Error('queue unavailable'))

            try {
                const res = await supertest(app)
                    .post(
                        `/api/projects/${scheduleHogFlow.team_id}/hog_flows/${scheduleHogFlow.id}/scheduled_invocations`
                    )
                    .send({})

                expect(res.status).toEqual(500)

                // The row outlives the request on the shared service, so a later flush would
                // publish a run that never entered cyclotron.
                await rowsService.flush()
                expect(produceSpy).not.toHaveBeenCalled()
            } finally {
                hub.HOG_INVOCATION_RESULTS_ENABLED = resultsEnabled
                produceSpy.mockRestore()
            }
        })

        it('queues invocation with empty variables when none provided', async () => {
            const res = await supertest(app)
                .post(`/api/projects/${scheduleHogFlow.team_id}/hog_flows/${scheduleHogFlow.id}/scheduled_invocations`)
                .send({})

            expect(res.status).toEqual(200)
            expect(res.body.status).toEqual('queued')
            expect(res.body.invocation_id).toBeDefined()
            expect(mockQueueInvocations).toHaveBeenCalledTimes(1)
        })
    })

    describe('hogflow in-flight count', () => {
        let countHogFlow: HogFlow
        let mockCountInFlightJobs: jest.Mock

        beforeEach(async () => {
            mockCountInFlightJobs = jest
                .fn()
                .mockResolvedValue({ count: 3, byAction: { delay_1: 2 }, positionUnknown: 1 })
            api['batchResolverProducer'] = fakeJobProducer({ countInFlightJobs: mockCountInFlightJobs })

            countHogFlow = await insertHogFlow({
                id: new UUIDT().toString(),
                name: 'test in-flight count hog flow',
                status: 'active',
                version: 1,
                exit_condition: 'exit_on_conversion',
                edges: [],
                actions: [],
                trigger: {
                    type: 'event',
                    filters: {},
                },
            })
        })

        afterEach(() => {
            api['batchResolverProducer'] = null
        })

        it('returns the in-flight job count for a workflow', async () => {
            const res = await supertest(app).get(
                `/api/projects/${countHogFlow.team_id}/hog_flows/${countHogFlow.id}/in_flight_count`
            )

            expect(res.status).toEqual(200)
            expect(res.body).toEqual({ count: 3, by_action: { delay_1: 2 }, position_unknown: 1 })
            expect(mockCountInFlightJobs).toHaveBeenCalledWith(countHogFlow.team_id, countHogFlow.id)
        })

        it('errors if missing hog flow', async () => {
            const res = await supertest(app).get(
                `/api/projects/${countHogFlow.team_id}/hog_flows/${new UUIDT().toString()}/in_flight_count`
            )

            expect(res.status).toEqual(404)
            expect(res.body.error).toEqual('Workflow not found')
        })

        it("errors when requesting another team's hog flow", async () => {
            const otherTeamId = await createTeam(hub.postgres, team.organization_id)

            const res = await supertest(app).get(
                `/api/projects/${otherTeamId}/hog_flows/${countHogFlow.id}/in_flight_count`
            )

            expect(res.status).toEqual(404)
            expect(res.body.error).toEqual('Workflow not found')
            expect(mockCountInFlightJobs).not.toHaveBeenCalled()
        })

        it('errors if the cyclotron producer is not configured', async () => {
            api['batchResolverProducer'] = null

            const res = await supertest(app).get(
                `/api/projects/${countHogFlow.team_id}/hog_flows/${countHogFlow.id}/in_flight_count`
            )

            expect(res.status).toEqual(503)
        })
    })

    describe('hogflow reschedule parked', () => {
        let rescheduleHogFlow: HogFlow
        let mockRescheduleParkedJobs: jest.Mock
        const sweepFloor = new Date('2025-06-01T00:10:00.000Z')
        const sweepUntil = new Date('2025-06-01T00:40:00.000Z')

        // Mirrors Django's mint (posthog/plugins/plugin_server_api.py) with the shared dev/test key.
        const mintToken = (teamId: number, hogFlowId: string, secret = 'local-dev-workflows-reschedule-jwt') =>
            jwt.sign({ team_id: teamId, hog_flow_id: hogFlowId }, secret, {
                audience: 'posthog:workflows:reschedule_parked',
                expiresIn: '2m',
            })
        const authFor = (teamId: number, hogFlowId: string) => ({
            Authorization: `Bearer ${mintToken(teamId, hogFlowId)}`,
        })

        beforeEach(async () => {
            mockRescheduleParkedJobs = jest.fn().mockResolvedValue({
                swept: 5,
                remaining: 2,
                done: false,
                sweepFloor,
                sweepUntil,
            })
            api['batchResolverProducer'] = fakeJobProducer({ rescheduleParkedJobs: mockRescheduleParkedJobs })

            rescheduleHogFlow = await insertHogFlow({
                id: new UUIDT().toString(),
                name: 'test reschedule hog flow',
                status: 'active',
                version: 1,
                exit_condition: 'exit_on_conversion',
                edges: [],
                actions: [],
                trigger: {
                    type: 'event',
                    filters: {},
                },
            })
        })

        afterEach(() => {
            api['batchResolverProducer'] = null
        })

        it('runs a sweep slice and returns the bounds for follow-up slices', async () => {
            const res = await supertest(app)
                .post(`/api/projects/${rescheduleHogFlow.team_id}/hog_flows/${rescheduleHogFlow.id}/reschedule_parked`)
                .set(authFor(rescheduleHogFlow.team_id, rescheduleHogFlow.id))
                .send({ action_ids: ['delay_1', 'wait_1'] })

            expect(res.status).toEqual(200)
            expect(res.body).toEqual({
                swept: 5,
                remaining: 2,
                done: false,
                sweep_floor: sweepFloor.toISOString(),
                sweep_until: sweepUntil.toISOString(),
            })
            expect(mockRescheduleParkedJobs).toHaveBeenCalledWith({
                teamId: rescheduleHogFlow.team_id,
                functionId: rescheduleHogFlow.id,
                actionIds: ['delay_1', 'wait_1'],
                sweepFloor: undefined,
                sweepUntil: undefined,
            })
        })

        it('parses passed-through bounds into dates', async () => {
            const res = await supertest(app)
                .post(`/api/projects/${rescheduleHogFlow.team_id}/hog_flows/${rescheduleHogFlow.id}/reschedule_parked`)
                .set(authFor(rescheduleHogFlow.team_id, rescheduleHogFlow.id))
                .send({
                    action_ids: ['delay_1'],
                    sweep_floor: sweepFloor.toISOString(),
                    sweep_until: sweepUntil.toISOString(),
                })

            expect(res.status).toEqual(200)
            expect(mockRescheduleParkedJobs).toHaveBeenCalledWith(expect.objectContaining({ sweepFloor, sweepUntil }))
        })

        it.each([
            ['missing action_ids', {}],
            ['empty action_ids', { action_ids: [] }],
            ['non-string action_ids', { action_ids: [42] }],
            ['too many action_ids', { action_ids: Array.from({ length: 101 }, (_, i) => `a${i}`) }],
            ['unparseable bounds', { action_ids: ['a'], sweep_floor: 'nope', sweep_until: 'nope' }],
            ['only one bound', { action_ids: ['a'], sweep_floor: '2025-06-01T00:10:00.000Z' }],
            [
                'floor after until',
                {
                    action_ids: ['a'],
                    sweep_floor: '2025-06-01T00:40:00.000Z',
                    sweep_until: '2025-06-01T00:10:00.000Z',
                },
            ],
        ])('rejects a bad body: %s', async (_desc, body) => {
            const res = await supertest(app)
                .post(`/api/projects/${rescheduleHogFlow.team_id}/hog_flows/${rescheduleHogFlow.id}/reschedule_parked`)
                .set(authFor(rescheduleHogFlow.team_id, rescheduleHogFlow.id))
                .send(body)

            expect(res.status).toEqual(400)
            expect(mockRescheduleParkedJobs).not.toHaveBeenCalled()
        })

        it("errors when requesting another team's hog flow", async () => {
            const otherTeamId = await createTeam(hub.postgres, team.organization_id)

            const res = await supertest(app)
                .post(`/api/projects/${otherTeamId}/hog_flows/${rescheduleHogFlow.id}/reschedule_parked`)
                .set(authFor(otherTeamId, rescheduleHogFlow.id))
                .send({ action_ids: ['delay_1'] })

            expect(res.status).toEqual(404)
            expect(mockRescheduleParkedJobs).not.toHaveBeenCalled()
        })

        it.each([
            ['no token', () => ({})],
            [
                'a token signed with the wrong key',
                () => ({
                    Authorization: `Bearer ${mintToken(rescheduleHogFlow.team_id, rescheduleHogFlow.id, 'wrong-key')}`,
                }),
            ],
            [
                "another workflow's token",
                () => ({ Authorization: `Bearer ${mintToken(rescheduleHogFlow.team_id, new UUIDT().toString())}` }),
            ],
            [
                "another team's token",
                () => ({ Authorization: `Bearer ${mintToken(rescheduleHogFlow.team_id + 1, rescheduleHogFlow.id)}` }),
            ],
        ])('rejects a request with %s', async (_desc, headers) => {
            const res = await supertest(app)
                .post(`/api/projects/${rescheduleHogFlow.team_id}/hog_flows/${rescheduleHogFlow.id}/reschedule_parked`)
                .set(headers())
                .send({ action_ids: ['delay_1'] })

            expect(res.status).toEqual(401)
            expect(mockRescheduleParkedJobs).not.toHaveBeenCalled()
        })

        it('fails closed when the reschedule JWT key is not provisioned', async () => {
            const savedJwt = api['rescheduleJwt']
            api['rescheduleJwt'] = new ScopedServiceJwt(PosthogJwtAudience.WORKFLOWS_RESCHEDULE_PARKED, '')
            try {
                const res = await supertest(app)
                    .post(
                        `/api/projects/${rescheduleHogFlow.team_id}/hog_flows/${rescheduleHogFlow.id}/reschedule_parked`
                    )
                    .set(authFor(rescheduleHogFlow.team_id, rescheduleHogFlow.id))
                    .send({ action_ids: ['delay_1'] })

                expect(res.status).toEqual(503)
                expect(mockRescheduleParkedJobs).not.toHaveBeenCalled()
            } finally {
                api['rescheduleJwt'] = savedJwt
            }
        })

        it('errors if the cyclotron producer is not configured', async () => {
            api['batchResolverProducer'] = null

            const res = await supertest(app)
                .post(`/api/projects/${rescheduleHogFlow.team_id}/hog_flows/${rescheduleHogFlow.id}/reschedule_parked`)
                .send({ action_ids: ['delay_1'] })

            expect(res.status).toEqual(503)
        })
    })

    describe('workflow step resume', () => {
        let mockResumeParkedSteps: jest.Mock
        const jobId = new UUIDT().toString().toLowerCase()
        const originKey = `${jobId}:task_node:3`
        const body = { origin_key: originKey, status: 'completed', result: { final_message: 'done' } }

        // Raw audience literal and Python claim names: the wire contract with Django's
        // WORKFLOWS_STEP_RESUME_JWT_PURPOSE, so drift on either side breaks here.
        const mintResumeToken = (
            teamId: number,
            key: string,
            { secret = 'local-dev-workflows-step-resume-jwt', audience = 'posthog:workflows:step_resume' } = {}
        ) => jwt.sign({ team_id: teamId, origin_key: key }, secret, { audience, expiresIn: '2m' })
        const resumeAuth = (teamId: number, key: string) => ({
            Authorization: `Bearer ${mintResumeToken(teamId, key)}`,
        })

        beforeEach(() => {
            mockResumeParkedSteps = jest.fn().mockResolvedValue(new Map([[jobId, 'delivered']]))
            api['batchResolverProducer'] = fakeJobProducer({ resumeParkedSteps: mockResumeParkedSteps })
        })

        afterEach(() => {
            api['batchResolverProducer'] = null
        })

        it('accepts a Django-minted token and wakes the parked step', async () => {
            const res = await supertest(app)
                .post(`/api/projects/${team.id}/workflow_steps/resume`)
                .set(resumeAuth(team.id, originKey))
                .send(body)

            expect(res.status).toEqual(200)
            expect(res.body).toEqual({ outcome: 'delivered' })
            expect(mockResumeParkedSteps).toHaveBeenCalledWith(team.id, [{ ...body, jobId, actionId: 'task_node' }])
        })

        it('asks the caller to retry while the worker still holds the job', async () => {
            mockResumeParkedSteps.mockResolvedValue(new Map([[jobId, 'job_running']]))

            const res = await supertest(app)
                .post(`/api/projects/${team.id}/workflow_steps/resume`)
                .set(resumeAuth(team.id, originKey))
                .send(body)

            expect(res.status).toEqual(409)
            expect(res.body).toEqual({ outcome: 'job_running' })
        })

        it.each([
            ['no token', () => ({})],
            [
                'a token signed with the wrong key',
                () => ({ Authorization: `Bearer ${mintResumeToken(team.id, originKey, { secret: 'wrong-key' })}` }),
            ],
            [
                "another step's token",
                () => ({ Authorization: `Bearer ${mintResumeToken(team.id, `${jobId}:task_node:2`)}` }),
            ],
            ["another team's token", () => ({ Authorization: `Bearer ${mintResumeToken(team.id + 1, originKey)}` })],
            [
                'a cancel-audience token',
                () => ({
                    Authorization: `Bearer ${mintResumeToken(team.id, originKey, {
                        audience: 'posthog:workflows:cancel_invocations',
                    })}`,
                }),
            ],
        ])('rejects a request with %s', async (_desc, headers) => {
            const res = await supertest(app)
                .post(`/api/projects/${team.id}/workflow_steps/resume`)
                .set(headers())
                .send(body)

            expect(res.status).toEqual(401)
            expect(mockResumeParkedSteps).not.toHaveBeenCalled()
        })

        it('rejects a body whose origin key is not a dispatch key', async () => {
            const res = await supertest(app)
                .post(`/api/projects/${team.id}/workflow_steps/resume`)
                .set(resumeAuth(team.id, 'nope'))
                .send({ ...body, origin_key: 'nope' })

            expect(res.status).toEqual(400)
            expect(mockResumeParkedSteps).not.toHaveBeenCalled()
        })

        it('fails closed when the step resume JWT key is not provisioned', async () => {
            const savedJwt = api['stepResumeJwt']
            api['stepResumeJwt'] = new ScopedServiceJwt(PosthogJwtAudience.WORKFLOWS_STEP_RESUME, '')
            try {
                const res = await supertest(app)
                    .post(`/api/projects/${team.id}/workflow_steps/resume`)
                    .set(resumeAuth(team.id, originKey))
                    .send(body)

                expect(res.status).toEqual(503)
                expect(mockResumeParkedSteps).not.toHaveBeenCalled()
            } finally {
                api['stepResumeJwt'] = savedJwt
            }
        })
    })

    describe('transactional email', () => {
        let mockQueueInvocations: jest.Mock
        let hogFlow: HogFlow
        const body = {
            to: 'user@example.com',
            distinct_id: 'distinct_A_1',
            variables: { reset_link: 'https://example.com/reset' },
        }

        // Raw audience literal and Python claim names: the wire contract with Django's
        // WORKFLOWS_TRANSACTIONAL_EMAIL_JWT_PURPOSE, so drift on either side breaks here.
        const mintToken = (
            teamId: number,
            hogFlowId: string,
            {
                secret = 'local-dev-workflows-transactional-email-jwt',
                audience = 'posthog:workflows:send_transactional_email',
                claims = {},
            }: { secret?: string; audience?: string; claims?: Record<string, string> } = {}
        ) => jwt.sign({ team_id: teamId, hog_flow_id: hogFlowId, ...claims }, secret, { audience, expiresIn: '2m' })
        const tokenFor = (route: string, teamId: number, hogFlowId: string) =>
            mintToken(teamId, hogFlowId, route.endsWith('/send') ? { claims: { kind: 'code_send' } } : {})

        const transactionalFlow = (
            trigger: 'api' | 'schedule',
            status: HogFlow['status'],
            category: 'transactional' | 'marketing' = 'transactional',
            inputs: Record<string, CyclotronInputType> = {}
        ): HogFlow =>
            new FixtureHogFlowBuilder()
                .withTeamId(team.id)
                .withStatus(status)
                .withExitCondition('exit_only_at_end')
                .withWorkflow({
                    actions: {
                        trigger: { type: 'trigger', config: { type: trigger } },
                        email: {
                            type: 'function_email',
                            config: { template_id: 'template-email', inputs, message_category_type: category },
                        },
                    },
                    edges: [{ from: 'trigger', to: 'email', type: 'continue' }],
                })
                .build()

        // The alerts on this endpoint key on these outcome labels.
        const outcomeCount = async (outcome: string): Promise<number> =>
            (await transactionalEmailRequestsTotal.get()).values.find((v) => v.labels.outcome === outcome)?.value ?? 0
        const stageCounts = async (): Promise<Record<string, number>> =>
            Object.fromEntries(
                (await transactionalEmailStageDurationMs.get()).values
                    .filter((v) => v.metricName === 'cdp_transactional_email_stage_duration_ms_count')
                    .map((v) => [String(v.labels.stage), v.value])
            )
        const stageCountChanges = (before: Record<string, number>, after: Record<string, number>) =>
            Object.fromEntries(
                Object.entries(after)
                    .map(([stage, count]) => [stage, count - (before[stage] ?? 0)])
                    .filter(([, change]) => change !== 0)
            )

        const send = (flowId: string, headers: Record<string, string>, payload: Record<string, unknown> = body) =>
            supertest(app)
                .post(`/api/projects/${team.id}/hog_flows/${flowId}/transactional_email`)
                .set(headers)
                .send(payload)

        let produceOutput: jest.SpyInstance
        const emailStatusRows = (): Record<string, unknown>[] =>
            produceOutput.mock.calls
                .filter(([output]) => output === 'email_status')
                .map(([, message]) => parseJSON(message.value.toString()))

        const sendAccepted = (flowId: string, payload: Record<string, unknown>) =>
            supertest(app)
                .post(`/api/projects/${team.id}/hog_flows/${flowId}/transactional_email/send`)
                .set({ Authorization: `Bearer ${tokenFor('transactional_email/send', team.id, flowId)}` })
                .send(payload)

        const sendOn = (
            route: string,
            flowId: string,
            headers: Record<string, string>,
            payload: Record<string, unknown>
        ) => supertest(app).post(`/api/projects/${team.id}/hog_flows/${flowId}/${route}`).set(headers).send(payload)

        const inDays = (days: number): string => new Date(Date.now() + days * DAY_MS).toISOString()
        const toClickHouseTime = (date: Date): string => date.toISOString().replace('T', ' ').replace('Z', '000')

        let queue: CyclotronJobQueuePostgresV2
        let manager: CyclotronV2Manager
        let cyclotron: Pool

        beforeAll(async () => {
            queue = new CyclotronJobQueuePostgresV2(100, hub)
            await queue.startAsProducer()
            manager = new CyclotronV2Manager({
                pool: { dbUrl: hub.CYCLOTRON_NODE_DATABASE_URL! },
                depthLimit: 1_000_000,
            })
            await manager.connect()
            cyclotron = new Pool({ connectionString: hub.CYCLOTRON_NODE_DATABASE_URL })
        })

        afterAll(async () => {
            await queue.stopProducer()
            await manager.disconnect()
            await cyclotron.end()
        })

        const useRealQueue = async (): Promise<void> => {
            await cyclotron.query(`DELETE FROM cyclotron_jobs WHERE queue_name = 'email'`)
            api['hogflowQueue'] = queue
            api['batchResolverProducer'] = manager
        }

        const storedJob = async (id: string) =>
            (await cyclotron.query('SELECT status, scheduled, priority, state FROM cyclotron_jobs WHERE id = $1', [id]))
                .rows[0]

        const idsAnEmailWorkerClaims = async (): Promise<string[]> => {
            const worker = new CyclotronV2Worker({
                pool: { dbUrl: hub.CYCLOTRON_NODE_DATABASE_URL! },
                queueName: 'email',
                batchMaxSize: 100,
                pollDelayMs: 10,
                includeEmptyBatches: true,
            })
            let claimed: string[] = []
            await new Promise<void>((resolve, reject) => {
                worker
                    // eslint-disable-next-line @typescript-eslint/require-await
                    .connect(async (batch) => {
                        claimed = batch.map((job) => job.id)
                        resolve()
                    })
                    .catch(reject)
            })
            await worker.disconnect()
            return claimed
        }

        const codeSend = {
            content: { subject: 'Reset your password', html: '<p>Hi {{ variables.name }}</p>', text: 'Hi' },
            from: { integrationId: 12, email: 'security@example.com', name: 'Example' },
            replyTo: ['help@example.com'],
            tracking: { captureEngagement: true },
        }

        beforeEach(async () => {
            produceOutput = jest.spyOn(api['emailStatusService']['outputs'], 'produce')
            mockQueueInvocations = jest.fn().mockResolvedValue(undefined)
            api['hogflowQueue'] = { queueInvocations: mockQueueInvocations } as any
            hogFlow = await insertHogFlow(transactionalFlow('api', 'active'))
            // The fixtures send to example.com, which publishes a null MX. Without this every send is refused.
            jest.spyOn(api['emailValidationService'], 'getRecipientSkipReason').mockResolvedValue(null)
        })

        afterEach(() => {
            jest.restoreAllMocks()
        })

        it('queues one run on the email fast lane with the recipient and the data', async () => {
            const queueAppMetric = jest.spyOn(api['invocationResultsService'].monitoringService, 'queueAppMetric')
            const queuedBefore = await outcomeCount('queued')
            const stagesBefore = await stageCounts()

            const res = await send(hogFlow.id, { Authorization: `Bearer ${mintToken(team.id, hogFlow.id)}` })

            expect(res.status).toEqual(202)
            expect(res.body).toEqual({
                status: 'queued',
                invocation_id: expect.any(String),
                scheduled_at: null,
                replayed: false,
                attachment_count: 0,
                attachment_bytes: 0,
            })
            expect(await outcomeCount('queued')).toEqual(queuedBefore + 1)
            // Without an Idempotency-Key the request makes no idempotency call.
            expect(stageCountChanges(stagesBefore, await stageCounts())).toEqual({
                auth: 1,
                validate: 1,
                load: 1,
                build: 1,
                checks: 1,
                queue_insert: 1,
                metrics_flush: 1,
                total: 1,
            })
            expect(mockQueueInvocations).toHaveBeenCalledTimes(1)
            const [invocation] = mockQueueInvocations.mock.calls[0][0]
            expect(invocation).toMatchObject({
                id: res.body.invocation_id,
                teamId: team.id,
                functionId: hogFlow.id,
                queue: 'email',
                queuePriority: 0,
                state: {
                    event: { distinct_id: 'distinct_A_1', properties: { to: 'user@example.com' } },
                    variables: { reset_link: 'https://example.com/reset' },
                    triggerMetricPending: true,
                },
            })
            // The email worker counts the run as triggered, so a count here would count it twice.
            expect(queueAppMetric).not.toHaveBeenCalledWith(
                expect.objectContaining({ metric_name: 'triggered' }),
                expect.anything()
            )
            expect(emailStatusRows()).toEqual([
                expect.objectContaining({
                    team_id: team.id,
                    message_id: res.body.invocation_id,
                    status: 'queued',
                    recipient: 'user@example.com',
                    function_id: hogFlow.id,
                }),
            ])
        })

        it('replies before Kafka acks the result and status rows', async () => {
            let ackProduce: () => void = () => {}
            const acked = new Promise<void>((resolve) => (ackProduce = resolve))
            produceOutput.mockImplementation(() => acked)
            const resultsOutputs = api['invocationResultsService'].invocationResultsRowsService['outputs']
            const produceResultRow = jest.spyOn(resultsOutputs, 'produce').mockImplementation(() => acked)
            const resultsEnabled = hub.HOG_INVOCATION_RESULTS_ENABLED
            hub.HOG_INVOCATION_RESULTS_ENABLED = true

            try {
                const res = await send(hogFlow.id, { Authorization: `Bearer ${mintToken(team.id, hogFlow.id)}` })

                expect(res.status).toEqual(202)
                expect(produceResultRow).toHaveBeenCalledWith(
                    'hog_invocation_results',
                    expect.objectContaining({ key: Buffer.from(res.body.invocation_id) })
                )
                expect(emailStatusRows()).toEqual([
                    expect.objectContaining({ message_id: res.body.invocation_id, status: 'queued' }),
                ])
            } finally {
                hub.HOG_INVOCATION_RESULTS_ENABLED = resultsEnabled
                ackProduce()
            }
        })

        describe('with an idempotency key', () => {
            let keyed: Record<string, unknown>
            const sendKeyed = (payload: Record<string, unknown> = keyed) =>
                send(hogFlow.id, { Authorization: `Bearer ${mintToken(team.id, hogFlow.id)}` }, payload)
            const sendKeyedOn = (route: 'transactional_email' | 'transactional_email/send', payload: object) =>
                supertest(app)
                    .post(`/api/projects/${team.id}/hog_flows/${hogFlow.id}/${route}`)
                    .set({ Authorization: `Bearer ${tokenFor(route, team.id, hogFlow.id)}` })
                    .send({ ...payload, idempotency_key: keyed.idempotency_key })
            const changedContent = { ...codeSend, content: { ...codeSend.content, subject: 'Your new code' } }
            const otherSenderId = codeSend.from.integrationId + 3
            const addresslessSend = { ...codeSend, from: { integrationId: codeSend.from.integrationId } }

            beforeEach(() => {
                keyed = { ...body, idempotency_key: `key-${new UUIDT().toString()}` }
            })

            it.each([
                ['a template send', 'transactional_email', body, body],
                ['a code send', 'transactional_email/send', { ...body, send: codeSend }, { ...body, send: codeSend }],
                [
                    'a code send after its named address resolved to another sender',
                    'transactional_email/send',
                    { ...body, send: codeSend },
                    { ...body, send: { ...codeSend, from: { ...codeSend.from, integrationId: otherSenderId } } },
                ],
                [
                    'a code send from a sender without an address',
                    'transactional_email/send',
                    { ...body, send: addresslessSend },
                    { ...body, send: addresslessSend },
                ],
            ] as const)(
                'returns the first send for a retry of %s and queues nothing new',
                async (_desc, route, first, retry) => {
                    const sent = await sendKeyedOn(route, first)
                    const replayed = await sendKeyedOn(route, retry)

                    expect(sent.status).toEqual(202)
                    expect(sent.body).toMatchObject({ replayed: false })
                    expect(replayed.status).toEqual(202)
                    expect(replayed.body).toEqual({ ...sent.body, replayed: true })
                    expect(mockQueueInvocations).toHaveBeenCalledTimes(1)
                    expect(emailStatusRows()).toEqual([
                        expect.objectContaining({ message_id: sent.body.invocation_id, status: 'queued' }),
                    ])
                }
            )

            it.each([
                [
                    'another recipient',
                    ['transactional_email', body],
                    ['transactional_email', { ...body, to: 'someone-else@example.com' }],
                ],
                [
                    'changed content',
                    ['transactional_email/send', { ...body, send: codeSend }],
                    ['transactional_email/send', { ...body, send: changedContent }],
                ],
                [
                    'the other route',
                    ['transactional_email', body],
                    ['transactional_email/send', { ...body, send: codeSend }],
                ],
                [
                    'another named sender',
                    ['transactional_email/send', { ...body, send: codeSend }],
                    [
                        'transactional_email/send',
                        { ...body, send: { ...codeSend, from: { ...codeSend.from, email: 'alerts@example.com' } } },
                    ],
                ],
                [
                    'another sender without an address',
                    ['transactional_email/send', { ...body, send: addresslessSend }],
                    [
                        'transactional_email/send',
                        { ...body, send: { ...addresslessSend, from: { integrationId: otherSenderId } } },
                    ],
                ],
                [
                    'a changed cc',
                    ['transactional_email/send', { ...body, send: { ...codeSend, cc: ['manager@example.com'] } }],
                    ['transactional_email/send', { ...body, send: { ...codeSend, cc: ['someone-else@example.com'] } }],
                ],
            ] as const)(
                'rejects the key for a request with %s',
                async (_desc, [firstRoute, first], [route, payload]) => {
                    await sendKeyedOn(firstRoute, first)

                    const res = await sendKeyedOn(route, payload)

                    expect(res.status).toEqual(422)
                    expect(res.body).toEqual({ error: 'idempotency_key_reused' })
                    expect(mockQueueInvocations).toHaveBeenCalledTimes(1)
                }
            )

            it('tells a retry to wait while the first request is still queueing', async () => {
                let finishQueueing: () => void = () => {}
                mockQueueInvocations.mockImplementationOnce(
                    () => new Promise<void>((resolve) => (finishQueueing = resolve))
                )
                const first = sendKeyed().then((res) => res)
                await waitForExpect(() => expect(mockQueueInvocations).toHaveBeenCalledTimes(1))

                const retry = await sendKeyed()
                finishQueueing()

                expect(retry.status).toEqual(409)
                expect((await first).status).toEqual(202)
                expect(mockQueueInvocations).toHaveBeenCalledTimes(1)
            })

            it('lets a retry send when the first request failed to queue', async () => {
                mockQueueInvocations.mockRejectedValueOnce(new Error('queue down'))

                const first = await sendKeyed()
                const retry = await sendKeyed()

                expect(first.status).toEqual(500)
                expect(retry.status).toEqual(202)
                expect(retry.body).toMatchObject({ replayed: false })
                expect(mockQueueInvocations).toHaveBeenCalledTimes(2)
            })

            it('returns the first scheduled send for a retry that names the same time in another offset', async () => {
                const scheduledAt = new Date(Date.now() + 2 * DAY_MS)
                scheduledAt.setUTCMilliseconds(0)
                const inBerlin = new Date(scheduledAt.getTime() + 2 * 60 * 60 * 1000)
                    .toISOString()
                    .replace('.000Z', '+02:00')

                const first = await sendKeyedOn('transactional_email', {
                    ...body,
                    scheduled_at: scheduledAt.toISOString(),
                })
                const retry = await sendKeyedOn('transactional_email', { ...body, scheduled_at: inBerlin })

                expect(retry.status).toEqual(202)
                expect(retry.body).toEqual({ ...first.body, replayed: true })
                const scheduledRow = expect.objectContaining({
                    message_id: first.body.invocation_id,
                    status: 'scheduled',
                    recipient: body.to,
                    scheduled_at: toClickHouseTime(scheduledAt),
                })
                expect(emailStatusRows()).toEqual([scheduledRow])
            })

            it('frees the key when the scheduled time is too far ahead', async () => {
                const tooFar = await sendKeyedOn('transactional_email', { ...body, scheduled_at: inDays(31) })
                const retry = await sendKeyedOn('transactional_email', { ...body, scheduled_at: inDays(2) })

                expect(tooFar.status).toEqual(400)
                expect(retry.status).toEqual(202)
                expect(retry.body).toMatchObject({ status: 'scheduled', replayed: false })
            })

            it('refuses a keyed send when no idempotency store is configured', async () => {
                const keys = api['transactionalEmailIdempotencyKeys']
                api['transactionalEmailIdempotencyKeys'] = new IdempotencyKeys(null, 'transactional-email')
                try {
                    const res = await sendKeyed()

                    expect(res.status).toEqual(503)
                    expect(res.body).toEqual({ error: 'idempotency_unavailable' })
                    expect(mockQueueInvocations).not.toHaveBeenCalled()
                } finally {
                    api['transactionalEmailIdempotencyKeys'] = keys
                }
            })
        })

        describe('with a scheduled_at', () => {
            beforeEach(async () => {
                await useRealQueue()
            })

            const sendAt = (route: 'transactional_email' | 'transactional_email/send', scheduledAt: string) =>
                sendOn(
                    route,
                    hogFlow.id,
                    { Authorization: `Bearer ${tokenFor(route, team.id, hogFlow.id)}` },
                    {
                        ...(route === 'transactional_email' ? body : { ...body, send: codeSend }),
                        scheduled_at: scheduledAt,
                    }
                )

            it.each(['transactional_email', 'transactional_email/send'] as const)(
                'parks a send on %s until its time on the fast lane',
                async (route) => {
                    const scheduledAt = new Date(Date.now() + 30 * DAY_MS).toISOString()

                    const res = await sendAt(route, scheduledAt)

                    expect(res.status).toEqual(202)
                    expect(res.body).toEqual({
                        status: 'scheduled',
                        invocation_id: expect.any(String),
                        scheduled_at: scheduledAt,
                        replayed: false,
                        attachment_count: 0,
                        attachment_bytes: 0,
                    })
                    const job = await storedJob(res.body.invocation_id)
                    expect(new Date(job.scheduled).toISOString()).toEqual(scheduledAt)
                    expect(job.priority).toEqual(0)
                    const { state } = parseJSON(job.state.toString())
                    expect(state).toMatchObject({ scheduledAt })
                    expect(await idsAnEmailWorkerClaims()).toEqual([])
                    expect(emailStatusRows()).toEqual([
                        expect.objectContaining({
                            message_id: res.body.invocation_id,
                            status: 'scheduled',
                            recipient: body.to,
                            function_id: hogFlow.id,
                            scheduled_at: toClickHouseTime(new Date(scheduledAt)),
                            status_at: toClickHouseTime(new Date(state.statusAt)),
                        }),
                    ])
                }
            )

            it.each([
                ['another scheduled time', inDays(2), inDays(3)],
                ['a scheduled time added', undefined, inDays(2)],
            ])('rejects the key for a retry with %s and keeps only the first job', async (_desc, first, retry) => {
                const idempotency_key = `key-${new UUIDT().toString()}`
                const sendKeyedAt = (scheduledAt: string | undefined) =>
                    sendOn(
                        'transactional_email/send',
                        hogFlow.id,
                        { Authorization: `Bearer ${tokenFor('transactional_email/send', team.id, hogFlow.id)}` },
                        { ...body, send: codeSend, idempotency_key, ...(scheduledAt && { scheduled_at: scheduledAt }) }
                    )
                const accepted = await sendKeyedAt(first)

                const res = await sendKeyedAt(retry)

                expect(res.status).toEqual(422)
                expect(res.body).toEqual({ error: 'idempotency_key_reused' })
                const emailJobs = await cyclotron.query(`SELECT id FROM cyclotron_jobs WHERE queue_name = 'email'`)
                expect(emailJobs.rows.map((row) => row.id)).toEqual([accepted.body.invocation_id])
            })

            it('sends at once when the time has passed', async () => {
                const res = await sendAt('transactional_email', new Date(Date.now() - 60_000).toISOString())

                expect(res.status).toEqual(202)
                expect(res.body).toMatchObject({ status: 'queued', scheduled_at: null })
                expect(await idsAnEmailWorkerClaims()).toEqual([res.body.invocation_id])
                expect(emailStatusRows()).toEqual([expect.objectContaining({ status: 'queued' })])
            })

            it.each([
                ['more than 30 days ahead', inDays(30.01), 'invalid_scheduled_at'],
                ['without an offset', '2026-12-01T09:00:00', 'invalid_request'],
                ['that is not a time', 'tomorrow', 'invalid_request'],
            ])('refuses a time %s and queues nothing', async (_desc, scheduledAt, outcome) => {
                const before = await outcomeCount(outcome)

                const res = await sendAt('transactional_email/send', scheduledAt)

                expect(res.status).toEqual(400)
                expect(await outcomeCount(outcome)).toEqual(before + 1)
                if (outcome === 'invalid_scheduled_at') {
                    expect(res.body).toEqual({ error: 'invalid_scheduled_at', reason: 'too_far' })
                }
                expect(
                    (await cyclotron.query(`SELECT 1 FROM cyclotron_jobs WHERE queue_name = 'email'`)).rowCount
                ).toEqual(0)
                expect(emailStatusRows()).toEqual([])
            })
        })

        it.each([
            ['a code send with rendered content', codeSend],
            [
                'a code send with html that has no text to derive',
                { ...codeSend, content: { subject: 'Hi', html: '<img src="https://example.com/a.png" alt="Hi">' } },
            ],
            ['a code send for a local template', { tracking: { captureEngagement: false } }],
            [
                'a code send with copies to addresses that use atext symbols',
                { ...codeSend, cc: ['jane=tag@example.com'], bcc: ['jane~tag@example.com'] },
            ],
        ])('stamps %s on the queued run', async (_desc, acceptedSend) => {
            const res = await sendAccepted(hogFlow.id, { ...body, send: acceptedSend })

            expect(res.status).toEqual(202)
            const [invocation] = mockQueueInvocations.mock.calls[0][0]
            expect(invocation.state.send).toEqual(acceptedSend)
        })

        it('queues a template send without an accepted send, even when the request carries one', async () => {
            const res = await send(
                hogFlow.id,
                { Authorization: `Bearer ${mintToken(team.id, hogFlow.id)}` },
                { ...body, send: codeSend }
            )

            expect(res.status).toEqual(202)
            const [invocation] = mockQueueInvocations.mock.calls[0][0]
            expect(invocation.state.send).toBeUndefined()
        })

        it('refuses a send on the accepted send route without the send', async () => {
            const invalidBefore = await outcomeCount('invalid_request')

            const res = await sendAccepted(hogFlow.id, body)

            expect(res.status).toEqual(400)
            expect(await outcomeCount('invalid_request')).toEqual(invalidBefore + 1)
            expect(mockQueueInvocations).not.toHaveBeenCalled()
        })

        it.each([
            [
                'a bcc address is suppressed',
                'recipient_suppressed',
                { bcc: ['hidden@example.com'] },
                () =>
                    jest
                        .spyOn(api['emailSuppressionService'], 'isSuppressed')
                        .mockImplementation((_teamId, email) => Promise.resolve(email === 'hidden@example.com')),
            ],
            [
                "a cc address's domain has no mail servers",
                'recipient_unreachable',
                { cc: ['copy@example.com'] },
                () =>
                    jest
                        .spyOn(api['emailValidationService'], 'getRecipientSkipReason')
                        .mockImplementation((_teamId, email) =>
                            Promise.resolve(email === 'copy@example.com' ? 'Skipping send: no mail servers.' : null)
                        ),
            ],
            ['a cc address is malformed', 'recipient_unreachable', { cc: ['copy@ph\u3002example.com'] }, () => {}],
        ] as const)('refuses the whole code send when %s', async (_desc, code, copies, refuse) => {
            refuse()

            const res = await sendAccepted(hogFlow.id, { ...body, send: { ...codeSend, ...copies } })

            expect(res.status).toEqual(422)
            expect(res.body).toEqual({ error: code })
            expect(mockQueueInvocations).not.toHaveBeenCalled()
        })

        describe('queued on Cyclotron Postgres', () => {
            let cyclotron: Pool
            let posthogDb: PostgresProxy
            let personsDb: PostgresProxy
            let bucket: BucketProxy
            let router: PostgresRouter
            let queueName: string
            let filesApi: CdpApi
            let filesApp: express.Application
            let filesServer: Server
            let invoice: StoredFile
            let receipt: StoredFile
            let large: StoredFile

            const personsReadFrom = (persons: PostgresPersonRepository): PersonReadRepository => ({
                fetchPerson: (teamId, distinctId, callerTag) => persons.fetchPerson(teamId, distinctId, { callerTag }),
                fetchPersonsByDistinctIds: (teamPersons, callerTag) =>
                    persons.fetchPersonsByDistinctIds(teamPersons, true, callerTag),
                fetchPersonsByPersonIds: (teamPersons, callerTag) =>
                    persons.fetchPersonsByPersonIds(teamPersons, true, callerTag),
                fetchDistinctIdsForPersons: (teamId, personIntIds, options) =>
                    persons.fetchDistinctIdsForPersons(teamId, personIntIds, options),
            })
            const apisOfOneTest: { cdpApi: CdpApi; server: Server }[] = []
            const buildFilesApi = async (settings: Partial<Hub> = {}): Promise<CdpApi> => {
                const producer = new EmailQueueOfOneTest(queueName, hub)
                await producer.startAsProducer()
                return new CdpApi(
                    {
                        ...hub,
                        CDP_EMAIL_ATTACHMENTS_TEAMS: `${team.id}`,
                        CDP_EMAIL_ATTACHMENTS_S3_ENDPOINT: bucket.endpoint,
                        CDP_EMAIL_ATTACHMENTS_S3_PREFIX: attachmentStoreConfig.CDP_EMAIL_ATTACHMENTS_S3_PREFIX,
                        ...settings,
                    },
                    {
                        ...cdpDeps,
                        postgres: router,
                        personRepository: personsReadFrom(new PostgresPersonRepository(router)),
                        idempotencyValkey: createIdempotencyValkeyPool(hub),
                    },
                    { hogQueue: createMockJobQueue(), hogflowQueue: producer }
                )
            }
            const servedForOneTest = async (settings: Partial<Hub>): Promise<express.Application> => {
                const cdpApi = await buildFilesApi(settings)
                const served = serve(cdpApi)
                apisOfOneTest.push({ cdpApi, server: served.listen(0, () => {}) })
                return served
            }
            const serve = (cdpApi: CdpApi): express.Application => {
                const served = setupExpressApp()
                served.use('/', cdpApi.router())
                return served
            }

            type QueuedJob = { id: string; status: string; send: Record<string, unknown>; stored: string }
            const queuedJobs = async (): Promise<QueuedJob[]> => {
                const { rows } = await cyclotron.query(
                    'SELECT id, status, state FROM cyclotron_jobs WHERE queue_name = $1 ORDER BY created',
                    [queueName]
                )
                return rows.map((row) => ({
                    id: row.id,
                    status: row.status,
                    send: parseJSON(row.state.toString()).state.send,
                    stored: row.state.toString('latin1'),
                }))
            }
            const queuedIds = async (): Promise<string[]> => (await queuedJobs()).map((job) => job.id)

            const reference = (file: StoredFile) => ({
                sha256: file.metadata.sha256,
                filename: 'invoice.pdf',
                content_type: 'application/pdf',
            })
            const newKey = () => `key-${new UUIDT().toString()}`
            type SendOptions = {
                acceptedSend?: object
                flowId?: string
                variables?: Record<string, string>
                distinctId?: string
                to?: string
                app?: express.Application
            }
            const sendOnFilesApi = (
                payload: Record<string, unknown>,
                { flowId = hogFlow.id, app: served = filesApp }: SendOptions = {}
            ) =>
                supertest(served)
                    .post(`/api/projects/${team.id}/hog_flows/${flowId}/transactional_email/send`)
                    .set({ Authorization: `Bearer ${tokenFor('transactional_email/send', team.id, flowId)}` })
                    .send(payload)
            const sendWithFiles = (
                key: string,
                attachments: object[],
                {
                    acceptedSend = codeSend as object,
                    variables = body.variables as Record<string, string>,
                    distinctId = body.distinct_id,
                    to = body.to,
                    ...options
                }: SendOptions = {}
            ) =>
                sendOnFilesApi(
                    {
                        ...body,
                        to,
                        distinct_id: distinctId,
                        variables,
                        idempotency_key: key,
                        send: { ...acceptedSend, attachments },
                    },
                    options
                )

            beforeAll(async () => {
                cyclotron = new Pool({ connectionString: hub.CYCLOTRON_NODE_DATABASE_URL })
                posthogDb = await PostgresProxy.start(new URL(hub.DATABASE_URL))
                personsDb = await PostgresProxy.start(new URL(hub.PERSONS_DATABASE_URL || hub.DATABASE_URL))
                bucket = await BucketProxy.start()
                router = new PostgresRouter({
                    ...hub,
                    DATABASE_URL: posthogDb.url,
                    DATABASE_READONLY_URL: posthogDb.url,
                    PERSONS_DATABASE_URL: personsDb.url,
                    PERSONS_READONLY_DATABASE_URL: personsDb.url,
                })
                queueName = `transactional-email-test-${randomUUID()}`
                filesApi = await buildFilesApi()
                filesApp = serve(filesApi)
                filesServer = filesApp.listen(0, () => {})
                invoice = await uploadAttachment(team.id, { filename: 'invoice.pdf' })
                receipt = await uploadAttachment(team.id, { filename: 'receipt.pdf' })
                large = await uploadAttachment(team.id, { filename: 'large.pdf' }, Buffer.alloc(28_800_000, 'a'))
            })

            beforeEach(async () => {
                await insertHogFunctionTemplate(hub.postgres, emailTemplate)
            })

            afterEach(async () => {
                posthogDb.releaseAll()
                personsDb.releaseAll()
                bucket.lastModifiedAgeMs = 0
                bucket.release('pass')
                await Promise.all(
                    apisOfOneTest.splice(0).map(({ cdpApi, server: served }) => {
                        served.close()
                        return cdpApi.stop()
                    })
                )
                await cyclotron.query('DELETE FROM cyclotron_jobs WHERE queue_name = $1', [queueName])
            })

            afterAll(async () => {
                filesServer.close()
                await filesApi.stop()
                await Promise.all([bucket.close(), posthogDb.close(), personsDb.close()])
                await router.end()
                await cyclotron.end()
            })

            const withFile = (fields: Record<string, unknown>) => ({
                ...codeSend,
                attachments: [{ ...reference(invoice), ...fields }],
            })
            const filenameOf = (length: number) => `${'x'.repeat(length - '.pdf'.length)}.pdf`
            const contentTypeOf = (length: number) => `application/${'x'.repeat(length - 'application/'.length)}`
            const contentIdOf = (length: number) => 'x'.repeat(length)
            const filenameReason = `filename can be at most ${ATTACHMENT_FILENAME_MAX_LENGTH} characters`
            const contentTypeReason = `content_type needs 1 to ${ATTACHMENT_CONTENT_TYPE_MAX_LENGTH} characters`
            const contentIdReason = `content_id needs 1 to ${ATTACHMENT_CONTENT_ID_MAX_LENGTH} characters`

            it.each<[string, () => object, () => object, string]>([
                [
                    'a field this version does not know',
                    () => ({ ...codeSend, priority: 'high' }),
                    () => codeSend,
                    '"priority"',
                ],
                [
                    'a content field this version does not know',
                    () => ({ ...codeSend, content: { ...codeSend.content, amp: '<p/>' } }),
                    () => codeSend,
                    '"amp"',
                ],
                [
                    'a sender field this version does not know',
                    () => ({ ...codeSend, from: { ...codeSend.from, replyName: 'Ops' } }),
                    () => codeSend,
                    '"replyName"',
                ],
                [
                    'a tracking field this version does not know',
                    () => ({ ...codeSend, tracking: { captureEngagement: true, pixel: false } }),
                    () => codeSend,
                    '"pixel"',
                ],
                [
                    'content without a body',
                    () => ({ ...codeSend, content: { subject: 'Hi', html: '', text: '' } }),
                    () => codeSend,
                    'content needs html or text',
                ],
                [
                    'content with an empty subject',
                    () => ({ ...codeSend, content: { subject: '', text: 'Hi' } }),
                    () => codeSend,
                    '"subject"',
                ],
                [
                    'a sender without an integration',
                    () => ({ ...codeSend, from: { email: 'security@example.com' } }),
                    () => codeSend,
                    '"integrationId"',
                ],
                ['no tracking choice', () => ({ content: codeSend.content }), () => codeSend, '"tracking"'],
                [
                    'more than 10 cc addresses',
                    () => ({ ...codeSend, cc: Array.from({ length: 11 }, (_, i) => `copy-${i}@example.com`) }),
                    () => codeSend,
                    '"cc"',
                ],
                [
                    'more than 10 files',
                    () => ({ ...codeSend, attachments: Array(11).fill(reference(invoice)) }),
                    () => codeSend,
                    '"attachments"',
                ],
                [
                    'a file hash that is not 64 lowercase hex characters',
                    () => withFile({ sha256: invoice.metadata.sha256.toUpperCase() }),
                    () => codeSend,
                    '"sha256"',
                ],
                ['a file without a name', () => withFile({ filename: '' }), () => codeSend, '"filename"'],
                [
                    'a file field this version does not know',
                    () => withFile({ disposition: 'inline' }),
                    () => codeSend,
                    '"disposition"',
                ],
                [
                    'an inline file instead of a reference',
                    () => ({
                        ...codeSend,
                        attachments: [
                            { filename: 'report.pdf', content: 'c2VjcmV0LWZpbGU=', contentType: 'application/pdf' },
                        ],
                    }),
                    () => codeSend,
                    '"sha256"',
                ],
                [
                    'a file name over the SES limit',
                    () => withFile({ filename: filenameOf(ATTACHMENT_FILENAME_MAX_LENGTH + 1) }),
                    () => withFile({ filename: filenameOf(ATTACHMENT_FILENAME_MAX_LENGTH) }),
                    filenameReason,
                ],
                [
                    'a content type over the SES limit',
                    () => withFile({ content_type: contentTypeOf(ATTACHMENT_CONTENT_TYPE_MAX_LENGTH + 1) }),
                    () => withFile({ content_type: contentTypeOf(ATTACHMENT_CONTENT_TYPE_MAX_LENGTH) }),
                    contentTypeReason,
                ],
                ['an empty content type', () => withFile({ content_type: '' }), () => withFile({}), contentTypeReason],
                [
                    'a content id over the SES limit',
                    () => withFile({ content_id: contentIdOf(ATTACHMENT_CONTENT_ID_MAX_LENGTH + 1) }),
                    () => withFile({ content_id: contentIdOf(ATTACHMENT_CONTENT_ID_MAX_LENGTH) }),
                    contentIdReason,
                ],
                ['an empty content id', () => withFile({ content_id: '' }), () => withFile({}), contentIdReason],
                [
                    'a file name that starts a new header line',
                    () => withFile({ filename: 'invoice.pdf\r\nBcc: someone@example.com' }),
                    () => withFile({ filename: 'invoice.pdf' }),
                    'filename cannot contain control characters',
                ],
                [
                    'a content type that starts a new header line',
                    () => withFile({ content_type: 'application/pdf\r\nBcc: someone@example.com' }),
                    () => withFile({}),
                    'content_type cannot contain control characters',
                ],
                [
                    'a content id with a control character',
                    () => withFile({ content_id: 'logo\n' }),
                    () => withFile({}),
                    'content_id cannot contain control characters',
                ],
                [
                    'a file type SES does not send',
                    () => withFile({ filename: 'setup.exe' }),
                    () => withFile({ filename: 'setup.exe.pdf' }),
                    'SES does not send .exe files, so setup.exe cannot be attached',
                ],
                [
                    'a file type SES does not send, in upper case',
                    () => withFile({ filename: 'Invoice.PDF.JS' }),
                    () => withFile({ filename: 'Invoice.PDF.JSON' }),
                    'SES does not send .js files, so Invoice.PDF.JS cannot be attached',
                ],
            ])(
                'refuses a code send with %s, naming it, queues nothing, and its key sends once it is fixed',
                async (_desc, refused, fixed, reason) => {
                    const invalidBefore = await outcomeCount('invalid_request')
                    const idempotency_key = newKey()

                    const res = await sendOnFilesApi({ ...body, idempotency_key, send: refused() })
                    const queuedOnRefusal = await queuedIds()
                    const retried = await sendOnFilesApi({ ...body, idempotency_key, send: fixed() })

                    expect(res.status).toEqual(400)
                    expect(res.body.error).toContain(reason)
                    expect(await outcomeCount('invalid_request')).toEqual(invalidBefore + 1)
                    expect(queuedOnRefusal).toEqual([])
                    expect(retried.status).toEqual(202)
                    expect(await queuedIds()).toEqual([retried.body.invocation_id])
                }
            )

            it('queues the references of the files it verified, without their bytes, answers their totals, and the worker delivers those files', async () => {
                const recipient = `${randomUUID()}@example.com`
                await insertIntegration(hub.postgres, team.id, {
                    id: codeSend.from.integrationId,
                    kind: 'email',
                    config: {
                        email: codeSend.from.email,
                        name: codeSend.from.name,
                        domain: 'example.com',
                        verified: true,
                        provider: 'ses',
                    },
                })
                const logo = {
                    sha256: receipt.metadata.sha256,
                    filename: 'logo.png',
                    content_type: 'image/png',
                    content_id: 'logo',
                }

                const generated = await flowThrough(
                    { exit },
                    [step('trigger', 'email'), step('email', 'exit')],
                    'transactional',
                    {
                        email: {
                            templating: 'liquid',
                            value: {
                                to: { email: '{{ event.properties.to | raw }}', name: '' },
                                cc: '',
                                bcc: '',
                                from: { integrationId: null },
                                replyTo: '',
                                subject: '',
                                preheader: '',
                                text: '',
                                html: '',
                            },
                        },
                    }
                )

                const res = await sendWithFiles(newKey(), [reference(invoice), logo], {
                    to: recipient,
                    flowId: generated.id,
                })

                expect(res.status).toBe(202)
                expect(res.body).toEqual({
                    status: 'queued',
                    invocation_id: expect.any(String),
                    scheduled_at: null,
                    replayed: false,
                    attachment_count: 2,
                    attachment_bytes: invoice.bytes.length + receipt.bytes.length,
                })
                const [job] = await queuedJobs()
                expect(job.id).toBe(res.body.invocation_id)
                expect(job.send).toEqual({
                    ...codeSend,
                    attachments: [
                        {
                            sha256: invoice.metadata.sha256,
                            filename: 'invoice.pdf',
                            contentType: 'application/pdf',
                            sizeBytes: invoice.bytes.length,
                        },
                        {
                            sha256: receipt.metadata.sha256,
                            filename: 'logo.png',
                            contentType: 'image/png',
                            contentId: 'logo',
                            sizeBytes: receipt.bytes.length,
                        },
                    ],
                })
                for (const file of [invoice, receipt]) {
                    expect(job.stored).not.toContain(file.bytes.toString('latin1'))
                    expect(job.stored).not.toContain(file.bytes.toString('base64'))
                }

                const ses = await startFakeSes({
                    [hub.SES_TRACKED_CONFIGURATION_SET]: { tracking: true },
                    [hub.SES_UNTRACKED_CONFIGURATION_SET]: { tracking: false },
                })
                const workerConfig = {
                    ...hub,
                    CDP_CYCLOTRON_BATCH_DELAY_MS: 10,
                    CDP_EMAIL_ATTACHMENTS_S3_PREFIX: attachmentStoreConfig.CDP_EMAIL_ATTACHMENTS_S3_PREFIX,
                }
                const worker = new CdpCyclotronWorkerEmail(
                    workerConfig,
                    createCdpConsumerDeps(hub),
                    new EmailQueueOfOneTest(queueName, workerConfig),
                    new InFlightRegistry({ budgetBytes: 2 ** 40, heapLimitBytes: 2 ** 40, maxInFlight: 1 }, () => 0)
                )
                worker.emailService.sesV2Client = sesClientFor(ses)
                await worker.start()
                try {
                    const delivered = await waitForExpect(() => {
                        expect(deliveredTo(ses, recipient)).toHaveLength(1)
                        return deliveredTo(ses, recipient)[0]
                    })
                    expect(delivered.attachments).toEqual([
                        {
                            filename: 'invoice.pdf',
                            contentType: 'application/pdf',
                            contentId: undefined,
                            inline: false,
                            bytes: invoice.bytes,
                        },
                        {
                            filename: 'logo.png',
                            contentType: 'image/png',
                            contentId: 'logo',
                            inline: true,
                            bytes: receipt.bytes,
                        },
                    ])
                } finally {
                    await worker.stop()
                    await ses.close()
                }
            })

            it.each([
                ['goes out now', undefined],
                ['is scheduled', inDays(1)],
            ])(
                'keeps the files of a send that %s until the last day a reschedule can move it to',
                async (_desc, scheduledAt) => {
                    const file = await uploadAttachment(team.id, {})
                    bucket.lastModifiedAgeMs = ATTACHMENT_LIFETIME_MS - 20 * DAY_MS

                    const res = await sendOnFilesApi({
                        ...body,
                        idempotency_key: newKey(),
                        send: { ...codeSend, attachments: [reference(file)] },
                        ...(scheduledAt && { scheduled_at: scheduledAt }),
                    })

                    expect(res.status).toBe(202)
                    expect(bucket.copied.filter((path) => path.endsWith(`/${file.metadata.sha256}`))).toHaveLength(1)
                }
            )

            it.each([
                ['the same files', () => [reference(invoice)], 202],
                ['other files', () => [reference(receipt)], 422],
            ])(
                'answers a retry of a keyed send with files that names %s from its first send, and queues one job',
                async (_name, retryFiles, status) => {
                    const key = newKey()
                    const sent = await sendWithFiles(key, [reference(invoice)])

                    const retried = await sendWithFiles(key, retryFiles())

                    expect(sent.status).toBe(202)
                    expect(retried.status).toBe(status)
                    expect(retried.body).toEqual(
                        status === 202 ? { ...sent.body, replayed: true } : { error: 'idempotency_key_reused' }
                    )
                    expect(await queuedIds()).toEqual([sent.body.invocation_id])
                }
            )

            const flowThrough = async (
                steps: SimpleHogFlowRepresentation['actions'],
                edges: SimpleHogFlowRepresentation['edges'],
                category: 'transactional' | 'marketing' = 'transactional',
                emailInputs: Record<string, CyclotronInputType> = {},
                emailConfig: { skip_frequency_cap?: boolean } = {}
            ): Promise<HogFlow> =>
                await insertHogFlow(
                    new FixtureHogFlowBuilder()
                        .withTeamId(team.id)
                        .withStatus('active')
                        .withExitCondition('exit_only_at_end')
                        .withWorkflow({
                            actions: {
                                trigger: { type: 'trigger', config: { type: 'api' } },
                                ...steps,
                                email: {
                                    type: 'function_email',
                                    config: {
                                        template_id: 'template-email',
                                        inputs: emailInputs,
                                        message_category_type: category,
                                        ...emailConfig,
                                    },
                                },
                            },
                            edges,
                        })
                        .build()
                )
            const delay = { type: 'delay', config: { delay_duration: '1h' } } as const
            const exit = { type: 'exit', config: {} } as const
            const step = (from: string, to: string) => ({ from, to, type: 'continue' as const })

            const shapesThatCannotCarryFiles: [string, () => Promise<HogFlow>, string][] = [
                [
                    'a delay before its email step',
                    () => flowThrough({ delay }, [step('trigger', 'delay'), step('delay', 'email')]),
                    'workflow_shape_not_supported',
                ],
                [
                    'an email step the frequency cap can hold',
                    () => flowThrough({}, [step('trigger', 'email')], 'marketing'),
                    'workflow_can_wait',
                ],
                [
                    'a marketing email step that skips the frequency cap, which the team sending cap can still hold',
                    () => flowThrough({}, [step('trigger', 'email')], 'marketing', {}, { skip_frequency_cap: true }),
                    'workflow_can_wait',
                ],
            ]

            it.each(shapesThatCannotCarryFiles)(
                'refuses a send with files to a workflow with %s, queues nothing, and releases the key',
                async (_name, arrange, code) => {
                    const flow = await arrange()
                    const key = newKey()
                    const stagesBefore = await stageCounts()

                    const res = await sendWithFiles(key, [reference(invoice)], { flowId: flow.id })
                    const stagesOfTheRefusal = stageCountChanges(stagesBefore, await stageCounts())
                    const queuedOnRefusal = await queuedIds()
                    const retry = await sendWithFiles(key, [reference(invoice)])

                    expect(res.status).toBe(400)
                    expect(res.body).toEqual({
                        error: code,
                        reason: expect.any(String),
                        fix: expect.any(String),
                    })
                    expect(stagesOfTheRefusal).toEqual({
                        auth: 1,
                        validate: 1,
                        load: 1,
                        build: 1,
                        idempotency: 1,
                        total: 1,
                    })
                    expect(queuedOnRefusal).toEqual([])
                    expect(retry.status).toBe(202)
                    expect(retry.body).toMatchObject({ replayed: false })
                    expect(await queuedIds()).toEqual([retry.body.invocation_id])
                }
            )

            it.each(shapesThatCannotCarryFiles)(
                'replays a keyed send with files after its workflow changed to %s',
                async (_name, arrange) => {
                    const flow = await flowThrough({ exit }, [step('trigger', 'email'), step('email', 'exit')])
                    const key = newKey()
                    const first = await sendWithFiles(key, [reference(invoice)], { flowId: flow.id })
                    expect(first.status).toBe(202)
                    const changed = await arrange()
                    await hub.postgres.query(
                        PostgresUse.COMMON_WRITE,
                        `UPDATE posthog_hogflow SET actions = changed.actions, edges = changed.edges
                         FROM posthog_hogflow changed WHERE posthog_hogflow.id = $1 AND changed.id = $2`,
                        [flow.id, changed.id],
                        'change-workflow-shape'
                    )
                    filesApi['hogFlowManager']['onHogFlowsReloaded'](team.id, [flow.id])

                    const retry = await sendWithFiles(key, [reference(invoice)], { flowId: flow.id })

                    expect(retry.status).toBe(202)
                    expect(retry.body).toEqual({ ...first.body, replayed: true })
                    expect(await queuedIds()).toEqual([first.body.invocation_id])
                }
            )

            it('refuses files from a team off the allowlist before it reserves the key, and queues nothing', async () => {
                const offTheList = await servedForOneTest({ CDP_EMAIL_ATTACHMENTS_TEAMS: `${team.id + 1}` })
                const stagesBefore = await stageCounts()

                const res = await sendWithFiles(newKey(), [reference(invoice)], { app: offTheList })

                expect(res.status).toBe(400)
                expect(res.body).toEqual({ error: 'field_not_accepted' })
                expect(stageCountChanges(stagesBefore, await stageCounts())).toEqual({ auth: 1, validate: 1, total: 1 })
                expect(await queuedIds()).toEqual([])
            })

            it.each<[string, () => Promise<{ file: StoredFile; fix: () => Promise<unknown> }>]>([
                [
                    'a file that was never uploaded',
                    () => {
                        const file = attachmentFile()
                        return Promise.resolve({ file, fix: () => uploadAttachment(team.id, {}, file.bytes) })
                    },
                ],
                [
                    'a file only another team uploaded',
                    async () => {
                        const file = await uploadAttachment(await createTeam(hub.postgres, team.organization_id), {})
                        return { file, fix: () => uploadAttachment(team.id, {}, file.bytes) }
                    },
                ],
            ])(
                'refuses a send with %s, queues nothing, and its key sends once that is fixed',
                async (_name, arrange) => {
                    const { file, fix } = await arrange()
                    const key = newKey()

                    const refused = await sendWithFiles(key, [reference(file)])
                    const queuedOnRefusal = await queuedIds()
                    await fix()
                    const retried = await sendWithFiles(key, [reference(file)])

                    expect(refused.status).toBe(400)
                    expect(refused.body).toEqual({ error: 'attachment_not_uploaded', sha256: file.metadata.sha256 })
                    expect(queuedOnRefusal).toEqual([])
                    expect(retried.status).toBe(202)
                    expect(await queuedIds()).toEqual([retried.body.invocation_id])
                }
            )

            const storedEmail = (email: Record<string, string>): Record<string, CyclotronInputType> => ({
                email: {
                    templating: 'liquid',
                    value: {
                        to: { email: '{{ event.properties.to }}', name: '' },
                        from: {},
                        subject: 'Your report',
                        text: 'Your report is attached',
                        ...email,
                    },
                },
            })
            const storedTemplateRendering = async (
                email: Record<string, string>,
                chunk: string
            ): Promise<SendOptions> => {
                const flow = await insertHogFlow(
                    transactionalFlow('api', 'active', 'transactional', storedEmail(email))
                )
                return {
                    flowId: flow.id,
                    variables: { chunk },
                    acceptedSend: { tracking: { captureEngagement: false } },
                }
            }
            const storedTemplateOnAFreshApi = async (): Promise<HeldSend> => ({
                options: await storedTemplateRendering({ html: '<p>{{ variables.chunk }}</p>' }, 'x'),
                app: await servedForOneTest({}),
            })
            const aPersonWithTheDistinctId = async (): Promise<string> => {
                const distinctId = `person-${randomUUID()}`
                await hub.personRepository.createPerson(
                    DateTime.now(),
                    {},
                    {},
                    {},
                    team.id,
                    null,
                    true,
                    new UUIDT().toString(),
                    { distinctId }
                )
                return distinctId
            }

            type HeldSend = { options?: SendOptions; app?: express.Application; fix?: () => void }
            const caught = async (query: Promise<HeldQuery>, expire: () => void): Promise<HeldQuery> => {
                const held = await query
                expire()
                return held
            }
            const realAbortSignalTimeout = AbortSignal.timeout.bind(AbortSignal)
            let verificationDeadline = new AbortController()
            const expireTheVerificationDeadline = (): void =>
                verificationDeadline.abort(new DOMException('The verification deadline passed', 'TimeoutError'))
            const queriesFor = (value: string) => (request: string) => request.includes(value)

            it.each<[string, () => Promise<HeldSend>]>([
                [
                    'no attachment store',
                    async () => ({ app: await servedForOneTest({ CDP_EMAIL_ATTACHMENTS_S3_BUCKET: '' }) }),
                ],
                [
                    'an attachment store that does not answer',
                    () => {
                        bucket.answer = 'refuse'
                        return Promise.resolve({ fix: () => bucket.release('pass') })
                    },
                ],
                [
                    'an attachment store whose HEAD outlasts the deadline, on a file that needs keeping',
                    () => {
                        bucket.answer = 'hold'
                        bucket.lastModifiedAgeMs = ATTACHMENT_LIFETIME_MS - SEND_NEEDS_FILES_FOR_MS + DAY_MS
                        void waitForExpect(() => expect(bucket.heldRequests).toBe(1)).then(
                            expireTheVerificationDeadline
                        )
                        return Promise.resolve({ fix: () => bucket.release('pass') })
                    },
                ],
                [
                    'an attachment store whose COPY outlasts the deadline, on a file that needs keeping',
                    () => {
                        bucket.answer = 'holdCopies'
                        bucket.lastModifiedAgeMs = ATTACHMENT_LIFETIME_MS - SEND_NEEDS_FILES_FOR_MS + DAY_MS
                        void waitForExpect(() => expect(bucket.heldRequests).toBe(1)).then(
                            expireTheVerificationDeadline
                        )
                        return Promise.resolve({ fix: () => bucket.release('pass') })
                    },
                ],
                [
                    'the recipient checks before the files use up the deadline',
                    async () => {
                        const to = `${randomUUID()}@example.com`
                        const lookup = posthogDb.hold(
                            (request) => request.includes('posthog_messagesuppression') && request.includes(to)
                        )
                        void lookup.then((held) => {
                            expireTheVerificationDeadline()
                            held.release()
                        })
                        return Promise.resolve({ options: { to } })
                    },
                ],
                [
                    'the template lookup of the email step fails',
                    async () => {
                        void posthogDb.hold(queriesFor('posthog_hogfunctiontemplate')).then((held) => held.drop())
                        return await storedTemplateOnAFreshApi()
                    },
                ],
                [
                    'the template lookup of the email step outlasts the deadline',
                    async () => {
                        void caught(
                            posthogDb.hold(queriesFor('posthog_hogfunctiontemplate')),
                            expireTheVerificationDeadline
                        )
                        return await storedTemplateOnAFreshApi()
                    },
                ],
                [
                    'the person lookup fails',
                    async () => {
                        const distinctId = await aPersonWithTheDistinctId()
                        void personsDb.hold(queriesFor(distinctId)).then((held) => held.drop())
                        return { options: { distinctId } }
                    },
                ],
                [
                    'the person lookup outlasts the deadline',
                    async () => {
                        const distinctId = await aPersonWithTheDistinctId()
                        void caught(personsDb.hold(queriesFor(distinctId)), expireTheVerificationDeadline)
                        return { options: { distinctId } }
                    },
                ],
                [
                    'the custom UTM tags of the email step render past the deadline',
                    async () => {
                        const distinctId = await aPersonWithTheDistinctId()
                        const flow = transactionalFlow('api', 'active', 'transactional', storedEmail({ html: 'x' }))
                        const emailStep = flow.actions.find((action) => action.type === 'function_email')!
                        const slowUtmTag = renderThatOutlastsTheLiquidLimit
                        Object.assign(emailStep.config, {
                            utm_tags_enabled: true,
                            utm_params: {
                                utm_source: slowUtmTag,
                                utm_medium: slowUtmTag,
                                utm_campaign: slowUtmTag,
                                utm_content: slowUtmTag,
                            },
                        })
                        const { id: flowId } = await insertHogFlow(flow)
                        const realNow = performance.now.bind(performance)
                        let skippedMs = 0
                        const clock = jest.spyOn(performance, 'now').mockImplementation(() => realNow() + skippedMs)
                        void personsDb.hold(queriesFor(distinctId)).then((held) => {
                            skippedMs = ATTACHMENT_VERIFICATION_DEADLINE_MS - 2 * LIQUID_RENDER_LIMIT_MS
                            held.release()
                        })
                        return {
                            options: {
                                flowId,
                                distinctId,
                                acceptedSend: { tracking: { captureEngagement: false } },
                            },
                            fix: () => clock.mockRestore(),
                        }
                    },
                ],
            ])(
                'answers 503 when %s without waiting on held work, queues nothing, asks the store for nothing after the answer, and its key sends once that is fixed',
                async (_name, arrange) => {
                    const deadlines = jest.spyOn(AbortSignal, 'timeout').mockImplementation((ms: number) => {
                        if (ms !== ATTACHMENT_VERIFICATION_DEADLINE_MS) {
                            return realAbortSignalTimeout(ms)
                        }
                        verificationDeadline = new AbortController()
                        return verificationDeadline.signal
                    })
                    const { options, app: refusingApp, fix } = await arrange()
                    const key = newKey()

                    const refused = await sendWithFiles(key, [reference(invoice)], { ...options, app: refusingApp })
                    const bucketRequestsAtTheAnswer = bucket.requests
                    posthogDb.releaseAll()
                    personsDb.releaseAll()
                    fix?.()
                    await waitForExpect(() => expect(bucket.heldRequests).toBe(0))
                    const queuedBeforeTheRetry = await queuedIds()
                    const bucketRequestsBeforeTheRetry = bucket.requests
                    deadlines.mockRestore()
                    const retried = await sendWithFiles(key, [reference(invoice)], options)

                    expect(refused.status).toBe(503)
                    expect(refused.body).toEqual({ error: 'delivery_unavailable' })
                    expect(queuedBeforeTheRetry).toEqual([])
                    expect(bucketRequestsBeforeTheRetry).toBe(bucketRequestsAtTheAnswer)
                    expect(retried.status).toBe(202)
                    expect(await queuedIds()).toEqual([retried.body.invocation_id])
                }
            )

            const roomForBodies = MESSAGE_MAX_BYTES - estimateMessageBytes([28_800_000])
            const bodyThatOverflows = 'x'.repeat(roomForBodies)
            const chunkThatFitsOnceNotTwice = 'x'.repeat(Math.ceil(roomForBodies / 2))
            const link = '<a href="https://example.com/">x</a>'
            const linksThatFitUntilTracked = link.repeat(Math.floor((roomForBodies * 0.7) / link.length))
            const contentOf = (html: string): SendOptions => ({
                acceptedSend: { ...codeSend, content: { subject: 'Your report', html } },
            })
            const chunkRenderedTwice = { html: '<p>{{ variables.chunk }}</p><p>{{ variables.chunk }}</p>' }
            const chunkAsPreheader = { html: '<p>Your report</p>', preheader: '{{ variables.chunk }}' }
            const renderThatOutlastsTheLiquidLimit =
                '{% for a in (1..1000) %}{% for b in (1..1000) %}{% for c in (1..1000) %}x{% endfor %}{% endfor %}{% endfor %}'
            const chunkRenderedTwiceBehindAnUnclosedTag = { html: `{% if variables.chunk %}${chunkRenderedTwice.html}` }

            it.each<[string, () => Promise<SendOptions>]>([
                ['content', () => Promise.resolve(contentOf('x'))],
                ['a stored template whose rendered body', () => storedTemplateRendering(chunkRenderedTwice, 'x')],
                [
                    'a stored template that fails to parse at accept, counted as no body, whose body',
                    () => storedTemplateRendering(chunkRenderedTwiceBehindAnUnclosedTag, chunkThatFitsOnceNotTwice),
                ],
                [
                    'content on the generated workflow, a trigger, an email step and an exit, whose body',
                    async () => ({
                        ...contentOf('x'),
                        flowId: (await flowThrough({ exit }, [step('trigger', 'email'), step('email', 'exit')])).id,
                    }),
                ],
            ])('accepts a send with files and %s fits beside them, and queues it', async (_name, arrange) => {
                const res = await sendWithFiles(newKey(), [reference(large)], await arrange())

                expect(res.status).toBe(202)
                expect(res.body).toMatchObject({ attachment_count: 1, attachment_bytes: large.bytes.length })
                expect(await queuedIds()).toEqual([res.body.invocation_id])
            })

            it.each<[string, () => Promise<SendOptions>]>([
                ['content', () => Promise.resolve(contentOf(bodyThatOverflows))],
                [
                    'content whose links grow once the worker tracks them',
                    () => Promise.resolve(contentOf(linksThatFitUntilTracked)),
                ],
                [
                    'a stored template that renders a chunk twice',
                    () => storedTemplateRendering(chunkRenderedTwice, chunkThatFitsOnceNotTwice),
                ],
                [
                    'a stored template whose preheader goes into the html',
                    () => storedTemplateRendering(chunkAsPreheader, bodyThatOverflows),
                ],
                [
                    'a stored template whose body grows with the person it sends to',
                    async () => ({
                        ...(await storedTemplateRendering(
                            { html: '<p>Your report</p>{% if person.id %}{{ variables.chunk }}{% endif %}' },
                            bodyThatOverflows
                        )),
                        distinctId: await aPersonWithTheDistinctId(),
                    }),
                ],
                [
                    'a stored template whose body renders only once the worker supplies its groups',
                    () =>
                        storedTemplateRendering(
                            { html: '<p>Your report</p>{% if groups %}{{ variables.chunk }}{% endif %}' },
                            bodyThatOverflows
                        ),
                ],
                [
                    'content whose subject',
                    () =>
                        Promise.resolve({
                            acceptedSend: {
                                ...codeSend,
                                content: { subject: bodyThatOverflows, html: '<p>Your report</p>' },
                            },
                        }),
                ],
                [
                    'a stored template whose rendered subject',
                    () => storedTemplateRendering({ subject: '{{ variables.chunk }}' }, bodyThatOverflows),
                ],
            ])(
                'refuses a send with files and %s too large to fit beside them, queues nothing, and its key sends smaller files',
                async (_name, arrange) => {
                    const options = await arrange()
                    const key = newKey()

                    const res = await sendWithFiles(key, [reference(large)], options)
                    const queuedOnRefusal = await queuedIds()
                    const retried = await sendWithFiles(key, [reference(invoice)], options)

                    expect(res.status).toBe(400)
                    expect(res.body).toEqual({
                        error: 'message_too_large',
                        message_bytes: expect.any(Number),
                        max_message_bytes: MESSAGE_MAX_BYTES,
                        attachment_bytes: large.bytes.length,
                    })
                    expect(res.body.message_bytes).toBeGreaterThan(MESSAGE_MAX_BYTES)
                    expect(queuedOnRefusal).toEqual([])
                    expect(retried.status).toBe(202)
                    expect(await queuedIds()).toEqual([retried.body.invocation_id])
                }
            )

            it('answers 503, not a template refusal, when the text of a text-only email step renders into the deadline, and queues nothing', async () => {
                const distinctId = await aPersonWithTheDistinctId()
                const { id: flowId } = await insertHogFlow(
                    transactionalFlow(
                        'api',
                        'active',
                        'transactional',
                        storedEmail({ text: renderThatOutlastsTheLiquidLimit })
                    )
                )
                const realNow = performance.now.bind(performance)
                let skippedMs = 0
                const clock = jest.spyOn(performance, 'now').mockImplementation(() => realNow() + skippedMs)
                void personsDb.hold(queriesFor(distinctId)).then((held) => {
                    skippedMs = ATTACHMENT_VERIFICATION_DEADLINE_MS - LIQUID_RENDER_LIMIT_MS / 2
                    held.release()
                })
                try {
                    const res = await sendWithFiles(newKey(), [reference(invoice)], {
                        flowId,
                        distinctId,
                        acceptedSend: { tracking: { captureEngagement: false } },
                    })

                    expect(res.status).toBe(503)
                    expect(res.body).toEqual({ error: 'delivery_unavailable' })
                    expect(await queuedIds()).toEqual([])
                } finally {
                    clock.mockRestore()
                }
            })

            it('queues a send with files whose email step fails to render at accept, and logs none of its variables', async () => {
                const secret = `reset-token-${randomUUID()}`
                const options = await storedTemplateRendering({ html: '{% include variables.chunk %}' }, secret)
                const emitted = emittedLogLines()

                let res: supertest.Response
                try {
                    res = await sendWithFiles(newKey(), [reference(invoice)], options)
                } finally {
                    emitted.stop()
                }

                expect(res.status).toBe(202)
                expect(await queuedIds()).toEqual([res.body.invocation_id])
                expect(
                    emitted.lines.some((line) =>
                        String(parseJSON(line).msg).endsWith('Could not render the email step of a send with files')
                    )
                ).toBe(true)
                expect(emitted.lines.join('')).not.toContain(secret)
            })

            const storedUtmValue = async (utmCampaign: string): Promise<SendOptions> => {
                const flow = transactionalFlow('api', 'active', 'transactional', storedEmail({ html: '<p>x</p>' }))
                const emailStep = flow.actions.find((action) => action.type === 'function_email')!
                Object.assign(emailStep.config, { utm_tags_enabled: true, utm_params: { utm_campaign: utmCampaign } })
                const { id: flowId } = await insertHogFlow(flow)
                return { flowId, acceptedSend: { tracking: { captureEngagement: false } } }
            }

            it.each<[string, string, () => Promise<SendOptions>]>([
                [
                    'goes over a template limit',
                    'email_render_limit_exceeded',
                    () => storedTemplateRendering({ html: renderThatOutlastsTheLiquidLimit }, 'x'),
                ],
                [
                    'has a body whose HTML and text together hold one Liquid tag over the limit',
                    'email_body_too_many_tags',
                    () =>
                        storedTemplateRendering(
                            {
                                html: '{{ variables.chunk }}'.repeat(EMAIL_BODY_TAG_LIMIT / 2 + 1),
                                text: '{% if variables.chunk %}x{% endif %}'.repeat(EMAIL_BODY_TAG_LIMIT / 4),
                            },
                            'x'
                        ),
                ],
                [
                    'has a body whose one Liquid block brings it one tag over the limit',
                    'email_body_too_many_tags',
                    () =>
                        storedTemplateRendering(
                            { html: `{% liquid\n${'echo variables.chunk\n'.repeat(EMAIL_BODY_TAG_LIMIT)}%}` },
                            'x'
                        ),
                ],
                [
                    'has a body whose quoted Liquid block opener comes before the Liquid tags over the limit',
                    'email_body_too_many_tags',
                    () =>
                        storedTemplateRendering(
                            { html: `{{ '{% liquid ' }}${'{{ variables.chunk }}'.repeat(EMAIL_BODY_TAG_LIMIT)}` },
                            'x'
                        ),
                ],
                [
                    'has a body whose one Liquid block, opened with an encoded space, brings it one tag over the limit',
                    'email_body_too_many_tags',
                    () =>
                        storedTemplateRendering(
                            { html: `{% liquid%20\n${'echo variables.chunk\n'.repeat(EMAIL_BODY_TAG_LIMIT)}%}` },
                            'x'
                        ),
                ],
                [
                    'has a body whose one Liquid block, opened after a blank only Liquid reads as blank, brings it one tag over the limit',
                    'email_body_too_many_tags',
                    () =>
                        storedTemplateRendering(
                            { html: `{%\u180Eliquid\n${'echo variables.chunk\n'.repeat(EMAIL_BODY_TAG_LIMIT)}%}` },
                            'x'
                        ),
                ],
                [
                    'has a body full of Liquid tags, which would take seconds to parse',
                    'email_body_too_many_tags',
                    () => storedTemplateRendering({ html: '{{ x }}'.repeat(100_000) }, 'x'),
                ],
                [
                    'has a subject full of Liquid tags, which would take seconds to parse',
                    'email_body_too_many_tags',
                    () => storedTemplateRendering({ subject: '{{ x }}'.repeat(100_000) }, 'x'),
                ],
                [
                    'has a UTM value one character over the length limit',
                    'utm_value_too_long',
                    () => storedUtmValue('x'.repeat(UTM_VALUE_LIMIT_CHARS + 1)),
                ],
                [
                    'has a UTM value full of Liquid tags, which would take seconds to parse',
                    'utm_value_too_long',
                    () => storedUtmValue('{{ x }}'.repeat(100_000)),
                ],
            ])(
                'refuses a send with files whose email step %s, queues nothing, and frees its key',
                async (_name, error, arrange) => {
                    const options = await arrange()
                    const key = newKey()

                    const refused = await sendWithFiles(key, [reference(invoice)], options)
                    const retried = await sendWithFiles(key, [reference(invoice)], options)

                    expect(refused.status).toBe(400)
                    expect(refused.body).toEqual({
                        error,
                        reason: expect.stringContaining('"function_email"'),
                        fix: expect.any(String),
                    })
                    expect(retried.body.error).toBe(error)
                    expect(await queuedIds()).toEqual([])
                }
            )

            it('accepts a send with files whose email editor design state holds more Liquid tags than the step may render', async () => {
                const inputs = storedEmail({ html: '<p>{{ variables.chunk }}</p>' })
                inputs.email.value.design = { body: '{{ variables.chunk }}'.repeat(EMAIL_BODY_TAG_LIMIT + 1) }
                const { id: flowId } = await insertHogFlow(transactionalFlow('api', 'active', 'transactional', inputs))

                const res = await sendWithFiles(newKey(), [reference(invoice)], {
                    flowId,
                    variables: { chunk: 'x' },
                    acceptedSend: { tracking: { captureEngagement: false } },
                })

                expect(res.status).toBe(202)
                expect(await queuedIds()).toEqual([res.body.invocation_id])
            })

            it('accepts a send without files whose email step body holds more Liquid tags than a send with files may', async () => {
                const options = await storedTemplateRendering(
                    { html: '{{ variables.chunk }}'.repeat(EMAIL_BODY_TAG_LIMIT + 1) },
                    'x'
                )

                const res = await sendWithFiles(newKey(), [], options)

                expect(res.status).toBe(202)
                expect(await queuedIds()).toEqual([res.body.invocation_id])
            })
        })

        it.each<[string, () => { payload: Record<string, unknown>; verify?: () => void }]>([
            [
                'the team is over its email quota',
                () => {
                    jest.spyOn(api['deps'].quotaLimiting, 'isTeamQuotaLimited').mockResolvedValue(true)
                    return { payload: body }
                },
            ],
            [
                "the lookup of the recipient's mail servers fails",
                () => {
                    jest.spyOn(api['emailValidationService'], 'getRecipientSkipReason').mockRestore()
                    const resolveMx = jest.mocked(api['emailValidationService']['resolver'].resolveMx)
                    resolveMx.mockRejectedValueOnce(Object.assign(new Error('queryMx ETIMEOUT'), { code: 'ETIMEOUT' }))
                    // A domain no other test sends to, so no cached verdict answers before the lookup.
                    const domain = `${new UUIDT().toString()}.example.org`
                    return {
                        payload: { ...body, to: `user@${domain}` },
                        verify: () => expect(resolveMx).toHaveBeenCalledWith(domain),
                    }
                },
            ],
        ])('queues a send when %s', async (_desc, arrange) => {
            const { payload, verify } = arrange()
            const queuedBefore = await outcomeCount('queued')

            const res = await send(hogFlow.id, { Authorization: `Bearer ${mintToken(team.id, hogFlow.id)}` }, payload)

            expect(res.status).toEqual(202)
            verify?.()
            expect(await outcomeCount('queued')).toEqual(queuedBefore + 1)
            expect(mockQueueInvocations).toHaveBeenCalledTimes(1)
        })

        it('queues the send for the email worker to hold when the suppression list cannot be read', async () => {
            jest.spyOn(api['emailSuppressionService'], 'isSuppressed').mockRejectedValueOnce(
                new SuppressionLookupError()
            )

            const res = await send(hogFlow.id, { Authorization: `Bearer ${mintToken(team.id, hogFlow.id)}` })

            expect(res.status).toEqual(202)
            expect(mockQueueInvocations).toHaveBeenCalledTimes(1)
        })

        it('refuses a send of a marketing email when the team is over its email quota', async () => {
            jest.spyOn(api['deps'].quotaLimiting, 'isTeamQuotaLimited').mockResolvedValue(true)
            const marketingFlow = await insertHogFlow(transactionalFlow('api', 'active', 'marketing'))
            const limitedBefore = await outcomeCount('quota_limited')

            const res = await send(marketingFlow.id, {
                Authorization: `Bearer ${mintToken(team.id, marketingFlow.id)}`,
            })

            expect(res.status).toEqual(429)
            expect(await outcomeCount('quota_limited')).toEqual(limitedBefore + 1)
            expect(mockQueueInvocations).not.toHaveBeenCalled()
        })

        describe.each([
            ['a template send', 'transactional_email', {}],
            ['a code send', 'transactional_email/send', { send: codeSend }],
        ])('for %s', (_kind, route, extra) => {
            it.each([
                [
                    'email sending is suspended for the project',
                    'sending_suspended',
                    () =>
                        jest
                            .spyOn(api['teamWorkflowsConfigService'], 'getEmailSendingSuspension')
                            .mockResolvedValueOnce('staff'),
                ],
                [
                    "the transactional email's sending is paused",
                    'sending_paused',
                    () =>
                        jest
                            .spyOn(api['hogFlowManager'], 'getHogFlowCheckingPrimaryOnMiss')
                            .mockResolvedValueOnce({ ...hogFlow, email_sending_paused_at: Date.now() }),
                ],
                [
                    'the recipient is suppressed',
                    'recipient_suppressed',
                    () => jest.spyOn(api['emailSuppressionService'], 'isSuppressed').mockResolvedValueOnce(true),
                ],
                [
                    "the recipient's domain has no mail servers",
                    'recipient_unreachable',
                    () =>
                        jest
                            .spyOn(api['emailValidationService'], 'getRecipientSkipReason')
                            .mockResolvedValueOnce('Skipping send: the domain has no reachable mail servers.'),
                ],
            ] as const)('refuses a send the email worker would skip because %s', async (_desc, code, refuse) => {
                refuse()
                const refusedBefore = await outcomeCount(code)
                const stagesBefore = await stageCounts()
                const keyed = { ...body, ...extra, idempotency_key: `key-${new UUIDT().toString()}` }
                const headers = { Authorization: `Bearer ${tokenFor(route, team.id, hogFlow.id)}` }

                const refused = await sendOn(route, hogFlow.id, headers, keyed)

                expect(refused.status).toEqual(422)
                expect(refused.body).toEqual({ error: code })
                expect(await outcomeCount(code)).toEqual(refusedBefore + 1)
                // The reserve and the release of the key count once, as one idempotency observation.
                expect(stageCountChanges(stagesBefore, await stageCounts())).toEqual({
                    auth: 1,
                    validate: 1,
                    load: 1,
                    build: 1,
                    idempotency: 1,
                    checks: 1,
                    total: 1,
                })
                expect(mockQueueInvocations).not.toHaveBeenCalled()
                expect(emailStatusRows()).toEqual([])

                const retry = await sendOn(route, hogFlow.id, headers, keyed)

                expect(retry.status).toEqual(202)
                expect(mockQueueInvocations).toHaveBeenCalledTimes(1)
            })

            it('replays a keyed send whose workflow stopped being active since it went out', async () => {
                const keyed = { ...body, ...extra, idempotency_key: `key-${new UUIDT().toString()}` }
                const headers = { Authorization: `Bearer ${tokenFor(route, team.id, hogFlow.id)}` }
                const first = await sendOn(route, hogFlow.id, headers, keyed)
                await hub.postgres.query(
                    PostgresUse.COMMON_WRITE,
                    `UPDATE posthog_hogflow SET status = 'draft' WHERE id = $1`,
                    [hogFlow.id],
                    'deactivate-workflow'
                )
                api['hogFlowManager']['onHogFlowsReloaded'](team.id, [hogFlow.id])

                const retry = await sendOn(route, hogFlow.id, headers, keyed)

                expect(retry.status).toEqual(202)
                expect(retry.body).toEqual({ ...first.body, replayed: true })
                expect(mockQueueInvocations).toHaveBeenCalledTimes(1)
            })
        })

        it.each([
            ['a valid address', { to: 'user@example.com' }, 202, 'queued'],
            ...[
                'jane=tag@example.com',
                'jane~tag@example.com',
                'jane#tag@example.com',
                "o'brien@example.com",
                'a!b$c%d&e*f/g?h^i`j|k~l@example.com',
                'jane@sub.example.co.uk',
            ].map((to) => [to, { to }, 202, 'queued'] as const),
            ...[
                'jane@bücher.example',
                'jane@[192.0.2.1]',
                '"jane doe"@example.com',
                'jane@localhost',
                '.jane@example.com',
                'jane.@example.com',
                'jane..doe@example.com',
            ].map((to) => [to, { to }, 422, 'recipient_unreachable'] as const),
            ['a domain with a fullwidth dot', { to: 'user@ph\uFF0Eexample.com' }, 422, 'recipient_unreachable'],
            ['an ideographic full stop', { to: 'user@ph\u3002example.com' }, 422, 'recipient_unreachable'],
            ['a zero-width space', { to: 'user\u200B@example.com' }, 422, 'recipient_unreachable'],
            ['no recipient', { to: undefined }, 400, 'invalid_request'],
            [
                'a bad address and no distinct_id',
                { to: 'user@ph\u3002example.com', distinct_id: '' },
                400,
                'invalid_request',
            ],
        ] as const)('answers a send to %s', async (_desc, overrides, expectedStatus, outcome) => {
            const warn = jest.spyOn(logger, 'warn')
            const before = await outcomeCount(outcome)

            const res = await send(
                hogFlow.id,
                { Authorization: `Bearer ${mintToken(team.id, hogFlow.id)}` },
                { ...body, ...overrides }
            )

            expect(res.status).toEqual(expectedStatus)
            expect(await outcomeCount(outcome)).toEqual(before + 1)
            expect(mockQueueInvocations).toHaveBeenCalledTimes(expectedStatus === 202 ? 1 : 0)
            if (expectedStatus === 422) {
                expect(res.body).toEqual({ error: 'recipient_unreachable' })
            }
            const validationLogs = warn.mock.calls.filter((args) =>
                args.includes('Transactional email request failed validation')
            )
            expect(validationLogs).toHaveLength(expectedStatus === 400 ? 1 : 0)
            expect(JSON.stringify(validationLogs)).not.toContain('example.com')
        })

        it.each([
            [
                'sending_suspended',
                422,
                [
                    'sending_suspended',
                    'sending_paused',
                    'recipient_suppressed',
                    'quota_limited',
                    'recipient_unreachable',
                ],
            ],
            [
                'sending_paused',
                422,
                ['sending_paused', 'recipient_suppressed', 'quota_limited', 'recipient_unreachable'],
            ],
            ['recipient_suppressed', 422, ['recipient_suppressed', 'quota_limited', 'recipient_unreachable']],
            ['quota_limited', 429, ['quota_limited', 'recipient_unreachable']],
        ] as const)('refuses with %s when it and every later check would refuse', async (code, status, reasons) => {
            // Marketing, because a transactional email bypasses the quota.
            const marketingFlow = await insertHogFlow(transactionalFlow('api', 'active', 'marketing'))
            const arrange: Record<(typeof reasons)[number], () => void> = {
                sending_suspended: () =>
                    jest
                        .spyOn(api['teamWorkflowsConfigService'], 'getEmailSendingSuspension')
                        .mockResolvedValue('staff'),
                sending_paused: () =>
                    jest
                        .spyOn(api['hogFlowManager'], 'getHogFlowCheckingPrimaryOnMiss')
                        .mockResolvedValue({ ...marketingFlow, email_sending_paused_at: Date.now() }),
                recipient_suppressed: () =>
                    jest.spyOn(api['emailSuppressionService'], 'isSuppressed').mockResolvedValue(true),
                quota_limited: () =>
                    jest.spyOn(api['deps'].quotaLimiting, 'isTeamQuotaLimited').mockResolvedValue(true),
                recipient_unreachable: () =>
                    jest
                        .spyOn(api['emailValidationService'], 'getRecipientSkipReason')
                        .mockResolvedValue('Skipping send: the domain has no reachable mail servers.'),
            }
            reasons.forEach((reason) => arrange[reason]())

            const res = await send(marketingFlow.id, {
                Authorization: `Bearer ${mintToken(team.id, marketingFlow.id)}`,
            })

            expect(res.status).toEqual(status)
            expect(res.body).toEqual({ error: code })
            expect(mockQueueInvocations).not.toHaveBeenCalled()
        })

        it('sends to a recipient whose only suppression is a spam complaint', async () => {
            await hub.postgres.query(
                PostgresUse.COMMON_WRITE,
                `INSERT INTO posthog_messagesuppression
                    (id, team_id, identifier, source, reason, transient_bounce_count,
                     suppressed, suppressed_at, deleted, created_at, updated_at)
                 VALUES (gen_random_uuid(), $1, $2, 'COMPLAINT', 'test row', 0,
                     true, NOW(), false, NOW(), NOW())`,
                [team.id, body.to],
                'test-insert-suppression'
            )

            const res = await send(hogFlow.id, { Authorization: `Bearer ${mintToken(team.id, hogFlow.id)}` })

            expect(res.status).toEqual(202)
            expect(mockQueueInvocations).toHaveBeenCalledTimes(1)
        })

        it.each([
            ['a workflow with another trigger', 'schedule', 'active'],
            ['a transactional email that is not active', 'api', 'draft'],
        ] as const)('refuses to run %s', async (_desc, trigger, status) => {
            const other = await insertHogFlow(transactionalFlow(trigger, status))

            const res = await send(other.id, { Authorization: `Bearer ${mintToken(team.id, other.id)}` })

            expect(res.status).toEqual(400)
            expect(res.body).toEqual({ error: 'not_sendable' })
            expect(mockQueueInvocations).not.toHaveBeenCalled()
        })

        it.each([
            ['transactional_email', body],
            ['transactional_email/send', { ...body, send: codeSend }],
        ])(
            'sends on %s under a workflow the replica does not have yet, reading the primary once',
            async (route, payload) => {
                const unseen = await _insertHogFlow(hub.postgres, transactionalFlow('api', 'active'))
                const query = hideHogFlowsFromReplica(hub.postgres, [unseen.id])
                const post = () =>
                    supertest(app)
                        .post(`/api/projects/${team.id}/hog_flows/${unseen.id}/${route}`)
                        .set({ Authorization: `Bearer ${tokenFor(route, team.id, unseen.id)}` })
                        .send(payload)

                expect((await post()).status).toEqual(202)
                expect((await post()).status).toEqual(202)

                expect(mockQueueInvocations).toHaveBeenCalledTimes(2)
                expect(
                    query.mock.calls.filter(
                        ([use, , , tag]) => use === PostgresUse.COMMON_WRITE && tag === 'fetchHogFlows'
                    )
                ).toHaveLength(1)
            }
        )

        it.each(['transactional_email', 'transactional_email/send'])(
            'authenticates every send on %s',
            async (route) => {
                const post = (headers: Record<string, string>) =>
                    supertest(app)
                        .post(`/api/projects/${team.id}/hog_flows/${hogFlow.id}/${route}`)
                        .set(headers)
                        .send({ ...body, send: codeSend })

                expect((await post({})).status).toEqual(401)
                expect(
                    (await post({ Authorization: `Bearer ${tokenFor(route, team.id + 1, hogFlow.id)}` })).status
                ).toEqual(401)
                expect(mockQueueInvocations).not.toHaveBeenCalled()
            }
        )

        it.each([
            ['a template send token on the code send route', 'transactional_email/send', 'transactional_email'],
            ['a code send token on the template send route', 'transactional_email', 'transactional_email/send'],
        ])('refuses %s', async (_desc, route, tokenRoute) => {
            const unauthorizedBefore = await outcomeCount('unauthorized')

            const res = await supertest(app)
                .post(`/api/projects/${team.id}/hog_flows/${hogFlow.id}/${route}`)
                .set({ Authorization: `Bearer ${tokenFor(tokenRoute, team.id, hogFlow.id)}` })
                .send({ ...body, send: codeSend })

            expect(res.status).toEqual(401)
            expect(await outcomeCount('unauthorized')).toEqual(unauthorizedBefore + 1)
            expect(mockQueueInvocations).not.toHaveBeenCalled()
        })

        it.each([
            ['no token', () => ({})],
            [
                "another workflow's token",
                () => ({ Authorization: `Bearer ${mintToken(team.id, new UUIDT().toString())}` }),
            ],
            ["another team's token", () => ({ Authorization: `Bearer ${mintToken(team.id + 1, hogFlow.id)}` })],
            [
                'a step-resume-audience token',
                () => ({
                    Authorization: `Bearer ${mintToken(team.id, hogFlow.id, {
                        audience: 'posthog:workflows:step_resume',
                    })}`,
                }),
            ],
        ])('rejects a request with %s', async (_desc, headers) => {
            const res = await send(hogFlow.id, headers())

            expect(res.status).toEqual(401)
            expect(mockQueueInvocations).not.toHaveBeenCalled()
        })

        describe('cancel and reschedule of a scheduled send', () => {
            type ManageAction = 'cancel' | 'reschedule'
            const mintManageToken = (
                teamId: number,
                messageId: string,
                action: ManageAction,
                {
                    secret = 'local-dev-workflows-transactional-email-jwt',
                    audience = 'posthog:workflows:manage_transactional_email',
                }: { secret?: string; audience?: string } = {}
            ) => jwt.sign({ team_id: teamId, message_id: messageId, action }, secret, { audience, expiresIn: '2m' })
            const manage = (
                action: ManageAction,
                messageId: string,
                payload: Record<string, unknown> = {},
                headers: Record<string, string> = {
                    Authorization: `Bearer ${mintManageToken(team.id, messageId, action)}`,
                }
            ) =>
                supertest(app)
                    .post(`/api/projects/${team.id}/transactional_emails/${messageId}/${action}`)
                    .set(headers)
                    .send(payload)

            const sendFor = async (scheduledAt: string | undefined): Promise<string> => {
                const res = await send(
                    hogFlow.id,
                    { Authorization: `Bearer ${mintToken(team.id, hogFlow.id)}` },
                    { ...body, ...(scheduledAt && { scheduled_at: scheduledAt }) }
                )
                expect(res.status).toEqual(202)
                return res.body.invocation_id
            }
            const scheduleSend = (): Promise<string> => sendFor(inDays(2))
            const claimedSend = async (): Promise<string> => {
                const id = await sendFor(undefined)
                expect(await idsAnEmailWorkerClaims()).toEqual([id])
                return id
            }
            const scheduledTime = async (id: string): Promise<string> =>
                new Date((await storedJob(id)).scheduled).toISOString()

            const observeKafka = (): (() => Record<string, any>[]) => {
                const outputs = api['emailStatusService']['outputs']['outputs'] as unknown as Record<
                    string,
                    { producer: KafkaProducerWrapper }
                >
                const observers = [...new Set(Object.values(outputs).map((output) => output.producer))].map(
                    (producer) => new KafkaProducerObserver(producer)
                )
                observers.forEach((observer) => observer.resetKafkaProducer())
                return () =>
                    observers.flatMap((observer) => observer.getProducedKafkaMessages().map((message) => message.value))
            }

            beforeEach(async () => {
                await useRealQueue()
            })

            afterEach(() => {
                api['batchResolverProducer'] = null
            })

            it.each([
                ['loads', true],
                ['fails to load', false],
            ])(
                'cancels a moved send before a worker claims it, and counts the run once, when its workflow %s',
                async (_desc, flowLoads) => {
                    const producedToKafka = observeKafka()
                    const resultsEnabled = hub.HOG_INVOCATION_RESULTS_ENABLED
                    hub.HOG_INVOCATION_RESULTS_ENABLED = true
                    try {
                        const messageId = await scheduleSend()
                        expect((await manage('reschedule', messageId, { scheduled_at: inDays(5) })).status).toEqual(200)
                        if (!flowLoads) {
                            jest.spyOn(api['hogFlowManager'], 'getHogFlowCheckingPrimaryOnMiss').mockRejectedValue(
                                new Error('database unavailable')
                            )
                        }

                        const first = await manage('cancel', messageId)
                        const repeat = await manage('cancel', messageId)

                        expect(first.status).toEqual(200)
                        expect(first.body).toEqual({ id: messageId, status: 'canceled' })
                        expect(repeat.status).toEqual(200)
                        expect(repeat.body).toEqual(first.body)
                        expect((await storedJob(messageId)).status).toEqual('canceled')
                        expect(await idsAnEmailWorkerClaims()).toEqual([])
                        const versioned = versionedAppSourceId(hogFlow.id, hogFlow.version)
                        await waitForExpect(() =>
                            expect(
                                producedToKafka()
                                    .filter((row) => row.metric_name === 'canceled' || row.metric_name === 'triggered')
                                    .map((row) => [row.app_source, row.app_source_id, row.metric_name, row.count])
                                    .sort()
                            ).toEqual(
                                [
                                    ['hog_flow', hogFlow.id, 'canceled', 1],
                                    ['hog_flow', hogFlow.id, 'triggered', 1],
                                    ...(flowLoads
                                        ? [
                                              [HOG_FLOW_VERSION_APP_SOURCE, versioned, 'canceled', 1],
                                              [HOG_FLOW_VERSION_APP_SOURCE, versioned, 'triggered', 1],
                                          ]
                                        : []),
                                ].sort()
                            )
                        )
                        const lifecycleRows = producedToKafka().filter(
                            (row) => row.function_kind && row.invocation_id === messageId
                        )
                        const scheduledAt = lifecycleRows[0].scheduled_at
                        expect(lifecycleRows).toEqual(
                            ['running', 'canceled', 'canceled'].map((status) =>
                                expect.objectContaining({
                                    invocation_id: messageId,
                                    function_kind: 'hog_flow',
                                    function_id: hogFlow.id,
                                    status,
                                    scheduled_at: scheduledAt,
                                })
                            )
                        )
                        expect(emailStatusRows()).toEqual([
                            expect.objectContaining({ message_id: messageId, status: 'scheduled' }),
                            expect.objectContaining({ message_id: messageId, status: 'scheduled' }),
                            ...[1, 2].map(() =>
                                expect.objectContaining({
                                    message_id: messageId,
                                    status: 'canceled',
                                    recipient: body.to,
                                    function_id: hogFlow.id,
                                })
                            ),
                        ])
                    } finally {
                        hub.HOG_INVOCATION_RESULTS_ENABLED = resultsEnabled
                    }
                }
            )

            it.each([
                ['an unknown message', () => Promise.resolve(new UUIDT().toString()), 404, { error: 'not_found' }],
                ['a message a worker has claimed', claimedSend, 409, { error: 'already_sending' }],
            ])('answers a cancel of %s without a status row', async (_desc, messageFor, status, expected) => {
                const messageId = await messageFor()
                const rowsBefore = emailStatusRows().length

                const res = await manage('cancel', messageId)

                expect(res.status).toEqual(status)
                expect(res.body).toEqual(expected)
                expect(emailStatusRows()).toHaveLength(rowsBefore)
            })

            it('moves a scheduled send and records it scheduled again with its recipient and new time', async () => {
                const messageId = await scheduleSend()
                const scheduledAt = inDays(3)

                const res = await manage('reschedule', messageId, { scheduled_at: scheduledAt })

                expect(res.status).toEqual(200)
                expect(res.body).toEqual({ id: messageId, status: 'scheduled', scheduled_at: scheduledAt })
                expect(await scheduledTime(messageId)).toEqual(scheduledAt)
                expect(parseJSON((await storedJob(messageId)).state.toString())).toMatchObject({
                    state: { scheduledAt },
                })
                expect(emailStatusRows().at(-1)).toEqual(
                    expect.objectContaining({
                        message_id: messageId,
                        status: 'scheduled',
                        recipient: body.to,
                        function_id: hogFlow.id,
                        scheduled_at: toClickHouseTime(new Date(scheduledAt)),
                    })
                )
            })

            const HOUR_MS = DAY_MS / 24
            it.each([
                [
                    'a send accepted to go out now and moved 30 days ahead, an hour before then',
                    undefined,
                    29.9,
                    31 * DAY_MS - HOUR_MS,
                    true,
                ],
                ['a send scheduled a day ahead and moved 30 days ahead', 1, 29.9, 31 * DAY_MS - HOUR_MS, true],
                [
                    'a send accepted to go out now and moved 30 days ahead, an hour after then',
                    undefined,
                    29.9,
                    31 * DAY_MS + HOUR_MS,
                    false,
                ],
                ['a send accepted to go out now and never moved', undefined, null, DAY_MS + HOUR_MS, false],
            ])(
                'replays a retry of %s only until a day after the latest time it can be due',
                async (_desc, scheduledInDays, movedToDays, retryAfterMs, replays) => {
                    const keys = api['transactionalEmailIdempotencyKeys']
                    const valkey = keys['valkey']!
                    const scope = `scope-${new UUIDT().toString()}`
                    api['transactionalEmailIdempotencyKeys'] = new IdempotencyKeys(valkey, scope)
                    const letStoreTimePass = (ms: number) =>
                        valkey.useClient({ name: 'test-store-clock' }, async (client) => {
                            for (const stored of await client.keys(`*${scope}*`)) {
                                const storedKey = stored.slice(client.options.keyPrefix?.length ?? 0)
                                const remainingMs = await client.pttl(storedKey)
                                if (remainingMs > ms) {
                                    await client.pexpire(storedKey, remainingMs - ms)
                                } else if (remainingMs >= 0) {
                                    await client.del(storedKey)
                                }
                            }
                        })
                    try {
                        const request = {
                            ...body,
                            ...(scheduledInDays !== undefined && { scheduled_at: inDays(scheduledInDays) }),
                            idempotency_key: `key-${scope}`,
                        }
                        const sendFirstRequest = () =>
                            send(hogFlow.id, { Authorization: `Bearer ${mintToken(team.id, hogFlow.id)}` }, request)
                        const first = await sendFirstRequest()
                        expect(first.status).toEqual(202)
                        if (movedToDays !== null) {
                            const moved = await manage('reschedule', first.body.invocation_id, {
                                scheduled_at: inDays(movedToDays),
                            })
                            expect(moved.status).toEqual(200)
                        }
                        await letStoreTimePass(retryAfterMs)

                        const retry = await sendFirstRequest()

                        expect(retry.status).toEqual(202)
                        expect(retry.body).toEqual({
                            ...first.body,
                            invocation_id: retry.body.invocation_id,
                            replayed: replays,
                        })
                        expect(retry.body.invocation_id === first.body.invocation_id).toEqual(replays)
                    } finally {
                        api['transactionalEmailIdempotencyKeys'] = keys
                    }
                }
            )

            it('answers a move whose key write fails with 503 and keeps the move, so a retry of it keeps the key', async () => {
                const keys = api['transactionalEmailIdempotencyKeys']
                const valkey = keys['valkey']!
                const scope = `scope-${new UUIDT().toString()}`
                api['transactionalEmailIdempotencyKeys'] = new IdempotencyKeys(valkey, scope)
                const failedWrites = async (): Promise<number> =>
                    (
                        await (register.getSingleMetric('cdp_hogflow_idempotency_operations_total') as Counter).get()
                    ).values.find(
                        (v) =>
                            v.labels.scope === scope &&
                            v.labels.operation === 'replay_until' &&
                            v.labels.outcome === 'failed'
                    )?.value ?? 0
                try {
                    const sendFirstRequest = () =>
                        send(
                            hogFlow.id,
                            { Authorization: `Bearer ${mintToken(team.id, hogFlow.id)}` },
                            { ...body, idempotency_key: `key-${scope}` }
                        )
                    const first = await sendFirstRequest()
                    expect(first.status).toEqual(202)
                    const messageId = first.body.invocation_id
                    const scheduledAt = inDays(3)

                    const outage = jest.spyOn(valkey, 'useClient').mockRejectedValue(new Error('connection lost'))
                    let moved: supertest.Response
                    try {
                        moved = await manage('reschedule', messageId, { scheduled_at: scheduledAt })
                    } finally {
                        outage.mockRestore()
                    }

                    expect(moved.status).toEqual(503)
                    expect(moved.body).toEqual({ error: 'idempotency_unavailable' })
                    expect(await scheduledTime(messageId)).toEqual(scheduledAt)
                    expect(emailStatusRows().at(-1)).toEqual(
                        expect.objectContaining({
                            message_id: messageId,
                            status: 'scheduled',
                            scheduled_at: toClickHouseTime(new Date(scheduledAt)),
                        })
                    )
                    expect(await failedWrites()).toEqual(1)

                    const movedAgain = await manage('reschedule', messageId, { scheduled_at: scheduledAt })
                    expect(movedAgain.status).toEqual(200)
                    await valkey.useClient({ name: 'test-store-clock' }, async (client) => {
                        for (const stored of await client.keys(`*${scope}*`)) {
                            const storedKey = stored.slice(client.options.keyPrefix?.length ?? 0)
                            const remainingMs = await client.pttl(storedKey)
                            await (remainingMs > DAY_MS + HOUR_MS
                                ? client.pexpire(storedKey, remainingMs - DAY_MS - HOUR_MS)
                                : client.del(storedKey))
                        }
                    })
                    const retry = await sendFirstRequest()
                    expect(retry.body).toEqual({ ...first.body, replayed: true })
                } finally {
                    api['transactionalEmailIdempotencyKeys'] = keys
                }
            })

            it('keeps the time of the reschedule that committed last when its status row arrives first', async () => {
                const messageId = await scheduleSend()
                const [earlier, later] = [inDays(3), inDays(4)]
                let releaseEarlier!: () => void
                const earlierHeld = new Promise<void>((resolve) => (releaseEarlier = resolve))
                const reschedule = manager.rescheduleUnclaimed.bind(manager)
                let reachedHold!: () => void
                const holding = new Promise<void>((resolve) => (reachedHold = resolve))
                jest.spyOn(manager, 'rescheduleUnclaimed').mockImplementationOnce(async (...args) => {
                    const result = await reschedule(...args)
                    reachedHold()
                    await earlierHeld
                    return result
                })

                const earlierRequest = manage('reschedule', messageId, { scheduled_at: earlier }).then((res) => res)
                await holding
                expect((await manage('reschedule', messageId, { scheduled_at: later })).status).toEqual(200)
                releaseEarlier()
                expect((await earlierRequest).status).toEqual(200)

                expect(await scheduledTime(messageId)).toEqual(later)
                const rows = emailStatusRows().filter((row) => row.status === 'scheduled')
                const latest = rows.reduce((a, b) => (BigInt(String(b.version)) > BigInt(String(a.version)) ? b : a))
                expect(latest.scheduled_at).toEqual(toClickHouseTime(new Date(later)))
            })

            it.each([
                ['a time that has passed', 0],
                ['a time that has passed, for a message older than 30 days', 31 * DAY_MS],
            ])('moves a send to now for %s', async (_desc, messageAgeMs) => {
                const messageId = new UUIDT(Date.now() - messageAgeMs).toString()
                await manager.createJob({
                    id: messageId,
                    teamId: team.id,
                    functionId: hogFlow.id,
                    queueName: 'email',
                    scheduled: new Date(Date.now() + DAY_MS),
                })
                const before = Date.now()

                const res = await manage('reschedule', messageId, {
                    scheduled_at: new Date(before - 60_000).toISOString(),
                })

                expect(res.status).toEqual(200)
                const movedTo = new Date(res.body.scheduled_at).getTime()
                expect(movedTo).toBeGreaterThanOrEqual(before)
                expect(movedTo).toBeLessThanOrEqual(Date.now())
                expect(await scheduledTime(messageId)).toEqual(res.body.scheduled_at)
                expect(await idsAnEmailWorkerClaims()).toEqual([messageId])
            })

            it.each([
                [
                    'a time more than 30 days after the message was created',
                    () => ({ scheduled_at: inDays(30.01) }),
                    400,
                    { error: 'invalid_scheduled_at', reason: 'too_far' },
                ],
                ['a time that is not a time', () => ({ scheduled_at: 'tomorrow' }), 400, { error: 'invalid_request' }],
                ['no time', () => ({}), 400, { error: 'invalid_request' }],
            ])('refuses a reschedule to %s and changes nothing', async (_desc, payload, status, expected) => {
                const messageId = await scheduleSend()
                const scheduledBefore = await scheduledTime(messageId)
                const rowsBefore = emailStatusRows().length

                const res = await manage('reschedule', messageId, payload())

                expect(res.status).toEqual(status)
                expect(res.body).toMatchObject(expected)
                expect(await scheduledTime(messageId)).toEqual(scheduledBefore)
                expect(emailStatusRows()).toHaveLength(rowsBefore)
            })

            it.each([
                ['an unknown message', () => Promise.resolve(new UUIDT().toString()), 404, { error: 'not_found' }],
                ['a message a worker has claimed', claimedSend, 409, { error: 'already_sending' }],
                [
                    'a canceled message',
                    async () => {
                        const id = await scheduleSend()
                        expect((await manage('cancel', id)).status).toEqual(200)
                        return id
                    },
                    409,
                    { error: 'canceled' },
                ],
            ])('answers a reschedule of %s without a status row', async (_desc, messageFor, status, expected) => {
                const messageId = await messageFor()
                const rowsBefore = emailStatusRows().length

                const res = await manage('reschedule', messageId, { scheduled_at: inDays(2) })

                expect(res.status).toEqual(status)
                expect(res.body).toEqual(expected)
                expect(emailStatusRows()).toHaveLength(rowsBefore)
            })

            describe.each(['cancel', 'reschedule'] as const)('on %s', (action) => {
                const otherAction: ManageAction = action === 'cancel' ? 'reschedule' : 'cancel'
                it.each<[string, (messageId: string) => Record<string, string>]>([
                    ['no token', () => ({})],
                    [
                        "another team's token",
                        (messageId) => ({ Authorization: `Bearer ${mintManageToken(team.id + 1, messageId, action)}` }),
                    ],
                    [
                        'a token signed with another key',
                        (messageId) => ({
                            Authorization: `Bearer ${mintManageToken(team.id, messageId, action, {
                                secret: 'not-the-signing-key',
                            })}`,
                        }),
                    ],
                    [
                        'a send token',
                        (messageId) => ({
                            Authorization: `Bearer ${mintManageToken(team.id, messageId, action, {
                                audience: 'posthog:workflows:send_transactional_email',
                            })}`,
                        }),
                    ],
                    [
                        "another message's token",
                        () => ({
                            Authorization: `Bearer ${mintManageToken(team.id, new UUIDT().toString(), action)}`,
                        }),
                    ],
                    [
                        "the other action's token",
                        (messageId) => ({
                            Authorization: `Bearer ${mintManageToken(team.id, messageId, otherAction)}`,
                        }),
                    ],
                ])('rejects a request with %s and leaves the send as it was', async (_desc, headers) => {
                    const messageId = await scheduleSend()
                    const before = await storedJob(messageId)

                    const res = await manage(action, messageId, { scheduled_at: inDays(3) }, headers(messageId))

                    expect(res.status).toEqual(401)
                    expect(await storedJob(messageId)).toEqual(before)
                })

                it('fails closed when the transactional email JWT key is not provisioned', async () => {
                    const messageId = await scheduleSend()
                    const before = await storedJob(messageId)
                    const savedJwt = api['manageTransactionalEmailJwt']
                    api['manageTransactionalEmailJwt'] = new ScopedServiceJwt(
                        PosthogJwtAudience.WORKFLOWS_MANAGE_TRANSACTIONAL_EMAIL,
                        ''
                    )
                    try {
                        const res = await manage(action, messageId, { scheduled_at: inDays(3) })

                        expect(res.status).toEqual(503)
                        expect(await storedJob(messageId)).toEqual(before)
                    } finally {
                        api['manageTransactionalEmailJwt'] = savedJwt
                    }
                })
            })
        })
    })

    describe('hogflow batch job resume', () => {
        let mockResume: jest.Mock
        const batchJobId = new UUIDT().toString().toLowerCase()
        const flowId = new UUIDT().toString().toLowerCase()

        // Raw audience literal and Python claim names: the wire contract with Django's
        // WORKFLOWS_RESUME_BATCH_JWT_PURPOSE.
        const mintBatchResumeToken = (
            claims: Record<string, unknown>,
            { secret = 'local-dev-workflows-step-resume-jwt', audience = 'posthog:workflows:resume_batch' } = {}
        ) => jwt.sign(claims, secret, { audience, expiresIn: '2m' })
        const resumeAuth = (teamId: number, claims: Record<string, unknown> = {}) => ({
            Authorization: `Bearer ${mintBatchResumeToken({
                team_id: teamId,
                hog_flow_id: flowId,
                batch_job_id: batchJobId,
                ...claims,
            })}`,
        })

        beforeEach(() => {
            mockResume = jest.fn()
            api['batchResolverProducer'] = fakeJobProducer({ resumeParkedBatchResolver: mockResume })
        })

        afterEach(() => {
            api['batchResolverProducer'] = null
        })

        it.each([
            ['resumed', 200],
            ['already_resumed', 200],
            ['job_running', 409],
            ['job_completed', 200],
            ['job_failed', 200],
            ['job_missing', 200],
        ])('answers %s with %s, so only a running resolver is retried', async (outcome, status) => {
            mockResume.mockResolvedValue(outcome)

            const res = await supertest(app)
                .post(`/api/projects/${team.id}/hog_flows/${flowId}/batch_jobs/${batchJobId}/resume`)
                .set(resumeAuth(team.id))
                .send({})

            expect(res.status).toEqual(status)
            expect(res.body).toEqual({ outcome })
            expect(mockResume).toHaveBeenCalledWith({ teamId: team.id, functionId: flowId, batchJobId })
        })

        it("rejects another run's token", async () => {
            const res = await supertest(app)
                .post(`/api/projects/${team.id}/hog_flows/${flowId}/batch_jobs/${batchJobId}/resume`)
                .set(resumeAuth(team.id, { batch_job_id: new UUIDT().toString() }))
                .send({})

            expect(res.status).toEqual(401)
            expect(mockResume).not.toHaveBeenCalled()
        })
    })

    describe('hogflow cancel invocations auth', () => {
        let mockCancelJobs: jest.Mock

        // Built with the raw audience literal and Python claim names: this is the wire contract
        // with Django's WORKFLOWS_CANCEL_INVOCATIONS_JWT_PURPOSE, so drift on either side breaks here.
        const mintCancelToken = (
            teamId: number,
            hogFlowId: string,
            { secret = 'local-dev-workflows-cancel-jwt', audience = 'posthog:workflows:cancel_invocations' } = {}
        ) => jwt.sign({ team_id: teamId, hog_flow_id: hogFlowId }, secret, { audience, expiresIn: '2m' })

        // No hog flow row exists for this id: cancel deliberately skips the flow lookup so it
        // keeps working for flows deleted with runs still parked.
        const cancelFlowId = new UUIDT().toString()
        const cancelAuth = (teamId: number, hogFlowId: string) => ({
            Authorization: `Bearer ${mintCancelToken(teamId, hogFlowId)}`,
        })

        beforeEach(() => {
            mockCancelJobs = jest.fn().mockResolvedValue({ marked: 3, remaining: 0, done: true })
            api['batchResolverProducer'] = fakeJobProducer({ cancelJobs: mockCancelJobs })
        })

        afterEach(() => {
            api['batchResolverProducer'] = null
        })

        it('accepts a Django-minted token and marks the flagged jobs', async () => {
            const res = await supertest(app)
                .post(`/api/projects/${team.id}/hog_flows/${cancelFlowId}/invocations/cancel`)
                .set(cancelAuth(team.id, cancelFlowId))
                .send({ all: true })

            expect(res.status).toEqual(200)
            expect(res.body).toEqual({ marked: 3, remaining: 0, done: true })
            expect(mockCancelJobs).toHaveBeenCalledWith(
                expect.objectContaining({ teamId: team.id, functionId: cancelFlowId, all: true })
            )
        })

        // A version-aware id check rejects every id the runs list hands the Cancel action,
        // because the invocation store issues UUIDTs. Only the shape must hold, to keep a
        // malformed id away from cancelJobs' ::uuid[] bind.
        it.each([
            ['ids the invocation store issues', [new UUIDT().toString(), new UUIDT().toString()], 200],
            ['an id that is not UUID-shaped', ['not-a-uuid'], 400],
        ])('cancelling by %s', async (_desc, invocationIds, expectedStatus) => {
            const res = await supertest(app)
                .post(`/api/projects/${team.id}/hog_flows/${cancelFlowId}/invocations/cancel`)
                .set(cancelAuth(team.id, cancelFlowId))
                .send({ invocation_ids: invocationIds })

            expect(res.status).toEqual(expectedStatus)
            if (expectedStatus === 200) {
                expect(mockCancelJobs).toHaveBeenCalledWith(expect.objectContaining({ jobIds: invocationIds }))
            } else {
                expect(mockCancelJobs).not.toHaveBeenCalled()
            }
        })

        it.each([
            ['no token', () => ({})],
            [
                'a token signed with the wrong key',
                () => ({
                    Authorization: `Bearer ${mintCancelToken(team.id, cancelFlowId, { secret: 'wrong-key' })}`,
                }),
            ],
            [
                "another workflow's token",
                () => ({ Authorization: `Bearer ${mintCancelToken(team.id, new UUIDT().toString())}` }),
            ],
            ["another team's token", () => ({ Authorization: `Bearer ${mintCancelToken(team.id + 1, cancelFlowId)}` })],
            [
                // Cancel and reschedule use separate keys now, so a reschedule-audience token is
                // rejected on audience regardless of which key signed it.
                'a reschedule-audience token',
                () => ({
                    Authorization: `Bearer ${mintCancelToken(team.id, cancelFlowId, {
                        audience: 'posthog:workflows:reschedule_parked',
                    })}`,
                }),
            ],
            [
                // The cancel key is dedicated: a cancel-audience token signed with the reschedule
                // sweep's key must be rejected, or splitting the keys would buy no real isolation.
                'a token signed with the reschedule key',
                () => ({
                    Authorization: `Bearer ${mintCancelToken(team.id, cancelFlowId, {
                        secret: 'local-dev-workflows-reschedule-jwt',
                    })}`,
                }),
            ],
        ])('rejects a request with %s', async (_desc, headers) => {
            const res = await supertest(app)
                .post(`/api/projects/${team.id}/hog_flows/${cancelFlowId}/invocations/cancel`)
                .set(headers())
                .send({ all: true })

            expect(res.status).toEqual(401)
            expect(mockCancelJobs).not.toHaveBeenCalled()
        })

        it('fails closed when the cancel JWT key is not provisioned', async () => {
            const savedJwt = api['cancelInvocationsJwt']
            api['cancelInvocationsJwt'] = new ScopedServiceJwt(PosthogJwtAudience.WORKFLOWS_CANCEL_INVOCATIONS, '')
            try {
                const res = await supertest(app)
                    .post(`/api/projects/${team.id}/hog_flows/${cancelFlowId}/invocations/cancel`)
                    .set(cancelAuth(team.id, cancelFlowId))
                    .send({ all: true })

                expect(res.status).toEqual(503)
                expect(mockCancelJobs).not.toHaveBeenCalled()
            } finally {
                api['cancelInvocationsJwt'] = savedJwt
            }
        })
    })

    describe('hogflow cancel batch job auth', () => {
        let mockCancelJobs: jest.Mock

        // Built with the raw audience literal and Python claim names: this is the wire contract
        // with Django's WORKFLOWS_CANCEL_BATCH_JWT_PURPOSE, so drift on either side breaks here.
        const batchFlowId = new UUIDT().toString()
        const batchJobId = new UUIDT().toString()

        const mintBatchToken = (
            teamId: number,
            hogFlowId: string,
            {
                secret = 'local-dev-workflows-cancel-jwt',
                audience = 'posthog:workflows:cancel_batch',
                batchJob = batchJobId,
            } = {}
        ) =>
            jwt.sign({ team_id: teamId, hog_flow_id: hogFlowId, batch_job_id: batchJob }, secret, {
                audience,
                expiresIn: '2m',
            })
        const batchAuth = (teamId: number, hogFlowId: string) => ({
            Authorization: `Bearer ${mintBatchToken(teamId, hogFlowId)}`,
        })
        const batchCancelUrl = (teamId: number) =>
            `/api/projects/${teamId}/hog_flows/${batchFlowId}/batch_jobs/${batchJobId}/cancel`

        beforeEach(() => {
            mockCancelJobs = jest.fn().mockResolvedValue({ marked: 2, remaining: 0, done: true })
            api['batchResolverProducer'] = fakeJobProducer({ cancelJobs: mockCancelJobs })
        })

        afterEach(() => {
            api['batchResolverProducer'] = null
        })

        it('accepts a Django-minted token and sweeps the batch run', async () => {
            const res = await supertest(app).post(batchCancelUrl(team.id)).set(batchAuth(team.id, batchFlowId)).send({})

            expect(res.status).toEqual(200)
            expect(res.body).toEqual({ marked: 2, remaining: 0, done: true })
            expect(mockCancelJobs).toHaveBeenCalledWith(
                expect.objectContaining({ teamId: team.id, functionId: batchFlowId, parentRunId: batchJobId })
            )
        })

        it.each([
            ['no token', () => ({})],
            [
                'a token signed with the wrong key',
                () => ({
                    Authorization: `Bearer ${mintBatchToken(team.id, batchFlowId, { secret: 'wrong-key' })}`,
                }),
            ],
            [
                "another workflow's token",
                () => ({ Authorization: `Bearer ${mintBatchToken(team.id, new UUIDT().toString())}` }),
            ],
            ["another team's token", () => ({ Authorization: `Bearer ${mintBatchToken(team.id + 1, batchFlowId)}` })],
            [
                // A captured token must not be replayable against a sibling batch run of the
                // same workflow: the batch_job_id claim has to match the URL.
                "another batch run's token",
                () => ({
                    Authorization: `Bearer ${mintBatchToken(team.id, batchFlowId, {
                        batchJob: new UUIDT().toString(),
                    })}`,
                }),
            ],
            [
                // The two cancel purposes share the cancel key, so the audience is the only thing
                // keeping an invocations-cancel token out of the batch route.
                'an invocations-cancel-audience token',
                () => ({
                    Authorization: `Bearer ${mintBatchToken(team.id, batchFlowId, {
                        audience: 'posthog:workflows:cancel_invocations',
                    })}`,
                }),
            ],
        ])('rejects a request with %s', async (_desc, headers) => {
            const res = await supertest(app).post(batchCancelUrl(team.id)).set(headers()).send({})

            expect(res.status).toEqual(401)
            expect(mockCancelJobs).not.toHaveBeenCalled()
        })

        it('fails closed when the batch cancel JWT key is not provisioned', async () => {
            const savedJwt = api['cancelBatchJwt']
            api['cancelBatchJwt'] = new ScopedServiceJwt(PosthogJwtAudience.WORKFLOWS_CANCEL_BATCH, '')
            try {
                const res = await supertest(app)
                    .post(batchCancelUrl(team.id))
                    .set(batchAuth(team.id, batchFlowId))
                    .send({})

                expect(res.status).toEqual(503)
                expect(mockCancelJobs).not.toHaveBeenCalled()
            } finally {
                api['cancelBatchJwt'] = savedJwt
            }
        })
    })

    // The test panel POSTs to /hog_flows/:id/invocations and runs the executor in-process —
    // it never enqueues into cyclotron. If the executor routes an email action onto the
    // dedicated email queue, nothing services that job and the workflow stalls on a
    // "Workflow will pause until …" log. The handler forces `isTest: true` so the
    // email branch always goes through EmailService directly on this path.
    describe('hog_flows/:id/invocations — email actions are sent inline despite queue routing', () => {
        let emailSpy: jest.SpyInstance
        let hogFlowId: string

        beforeEach(async () => {
            await insertIntegration(hub.postgres, team.id, {
                id: 1,
                kind: 'email',
                config: {
                    email: 'sender@posthog.com',
                    name: 'Test Sender',
                    domain: 'posthog.com',
                    verified: true,
                    provider: 'maildev',
                },
            })

            await insertHogFunctionTemplate(hub.postgres, {
                id: 'template-cdp-api-test-panel-email',
                name: 'CDP API Test Panel Email',
                code: `sendEmail(inputs.email)`,
                inputs_schema: [
                    {
                        type: 'native_email',
                        key: 'email',
                        label: 'Email message',
                        integration: 'email',
                        required: true,
                        default: {
                            to: { email: '', name: '' },
                            from: { email: '', name: '' },
                            subject: '',
                            text: 'Hello!',
                            html: '<div>Hello!</div>',
                        },
                        secret: false,
                        description: '',
                        templating: 'liquid',
                    },
                ],
            })

            const hogFlow = new FixtureHogFlowBuilder()
                .withTeamId(team.id)
                .withStatus('active')
                .withExitCondition('exit_only_at_end')
                .withWorkflow({
                    actions: {
                        trigger: {
                            type: 'trigger',
                            config: { type: 'event', filters: HOG_FILTERS_EXAMPLES.no_filters.filters ?? {} },
                        },
                        email_1: {
                            type: 'function_email',
                            config: {
                                template_id: 'template-cdp-api-test-panel-email',
                                inputs: {
                                    email: {
                                        value: {
                                            to: { email: 'recipient@example.com', name: 'Recipient' },
                                            from: { integrationId: 1, email: 'sender@posthog.com' },
                                            subject: 'Test panel email',
                                            text: 'hello from test panel',
                                            html: '<p>hello from test panel</p>',
                                        },
                                    },
                                },
                            },
                        },
                        exit: { type: 'exit', config: {} },
                    },
                    edges: [
                        { from: 'trigger', to: 'email_1', type: 'continue' },
                        { from: 'email_1', to: 'exit', type: 'continue' },
                    ],
                })
                .build()
            const inserted = await insertHogFlow(hogFlow)
            hogFlowId = inserted.id

            // Stub EmailService so the test doesn't depend on a running maildev SMTP. The spy
            // captures whether the inline path was taken — that's the assertion that proves the fix.
            emailSpy = jest
                .spyOn(api['hogExecutorAsync']['deps'].emailService, 'executeSendEmail')
                .mockImplementation((invocation: any) =>
                    Promise.resolve({
                        invocation,
                        finished: true,
                        emailSendResult: { status: 'accepted' },
                        logs: [],
                        metrics: [
                            {
                                team_id: invocation.teamId,
                                app_source_id: invocation.parentRunId ?? invocation.functionId,
                                instance_id: invocation.state.actionId || invocation.id,
                                metric_kind: 'email',
                                metric_name: 'email_sent',
                                count: 1,
                            },
                        ],
                        capturedPostHogEvents: [],
                        warehouseWebhookPayloads: [],
                        messageAssets: [],
                        conversionWatchers: [],
                    })
                )
        })

        afterEach(() => {
            emailSpy.mockRestore()
        })

        it.each([
            { status: 'accepted' },
            { status: 'skipped', reason: 'The recipient has no reachable mail servers.' },
        ])('returns the inline email outcome %j without routing to the email queue', async (emailSendResult) => {
            emailSpy.mockImplementation((invocation: any) =>
                Promise.resolve({
                    invocation,
                    finished: true,
                    emailSendResult,
                    logs: [],
                    metrics: [],
                    capturedPostHogEvents: [],
                    warehouseWebhookPayloads: [],
                    messageAssets: [],
                    conversionWatchers: [],
                })
            )
            const res = await supertest(app).post(`/api/projects/${team.id}/hog_flows/${hogFlowId}/invocations`).send({
                globals,
                configuration: {},
                current_action_id: 'email_1',
            })

            expect(res.status).toBe(200)
            expect(res.body.status).toBe('success')
            expect(res.body.emailSendResult).toEqual(emailSendResult)
            expect(res.body.errors).toEqual([])
            // EmailService was called inline — proving the test endpoint forced inline delivery
            // even though the team would normally be routed to the email queue.
            expect(emailSpy).toHaveBeenCalledTimes(1)
            // The "Workflow will pause until …" log only appears when the executor routes the
            // invocation to a different queue. It must NOT be present on the test panel response.
            const pauseLog = res.body.logs.find((l: any) =>
                String(l.message ?? '').startsWith('Workflow will pause until')
            )
            expect(pauseLog).toBeUndefined()
            // executeCurrentAction advances past the email step after the inline send — the
            // response's nextActionId proves the workflow continued to the next action.
            expect(res.body.nextActionId).toBe('exit')
        })
    })
    describe('transactional email attachment uploads', () => {
        const LARGE_DAILY_CAP = 50_000_000_000
        let store: S3AttachmentStore
        let redis: RedisV2
        let teamId: number
        let otherTeamId: number

        const mintUploadTokenAsTheDjangoRouteDoes = (
            forTeamId: number,
            claims: Record<string, string> = { kind: 'attachment_upload' },
            secret = 'local-dev-workflows-transactional-email-jwt'
        ) =>
            jwt.sign({ team_id: forTeamId, ...claims }, secret, {
                audience: 'posthog:workflows:send_transactional_email',
                expiresIn: '2m',
            })

        const requestUploads = (
            forTeamId: number,
            body: object,
            token = mintUploadTokenAsTheDjangoRouteDoes(forTeamId)
        ) =>
            supertest(app)
                .post(`/api/projects/${forTeamId}/transactional_email/attachments/uploads`)
                .set({ Authorization: `Bearer ${token}` })
                .send(body)

        type TestFile = { bytes: Buffer; sha256: string }
        const fileOf = (bytes: Buffer): TestFile => ({
            bytes,
            sha256: createHash('sha256').update(bytes).digest('hex'),
        })
        const pdf = (): TestFile => fileOf(Buffer.from(`%PDF-1.4 ${randomBytes(16).toString('hex')}`))
        const asked = (...files: TestFile[]) => ({
            files: files.map((f) => ({ sha256: f.sha256, size: f.bytes.length, content_type: 'application/pdf' })),
        })
        const sized = (...sizes: number[]) => ({
            files: sizes.map((size) => ({ sha256: randomBytes(32).toString('hex'), size })),
        })

        const uploadsFor = (
            teams: string,
            {
                maxBytesPerTeamDay = LARGE_DAILY_CAP,
                attachmentStore = store as S3AttachmentStore | null,
                counter = redis as RedisV2 | null,
            } = {}
        ): AttachmentUploads => new AttachmentUploads(attachmentStore, counter, { teams, maxBytesPerTeamDay })

        const putBytesWithoutSignedContentLength = async (slot: Record<string, any>, body: Buffer): Promise<number> =>
            (
                await globalThis.fetch(slot.url, {
                    method: slot.method,
                    headers: Object.fromEntries(
                        Object.entries(slot.headers as Record<string, string>).filter(
                            ([name]) => name.toLowerCase() !== 'content-length'
                        )
                    ),
                    body: new Uint8Array(body),
                })
            ).status
        const statusesOf = (res: supertest.Response): string[] =>
            res.body.files.map((f: { status: string }) => f.status)

        beforeAll(() => {
            store = buildAttachmentStore({
                ...getDefaultCdpConfig(),
                CDP_EMAIL_ATTACHMENTS_S3_PREFIX: `attachments-api-test/${Date.now()}`,
            })!
            redis = createIdempotencyValkeyPool(hub)!
        })

        beforeEach(async () => {
            teamId = await createTeam(hub.postgres, team.organization_id)
            otherTeamId = await createTeam(hub.postgres, team.organization_id)
            api['attachmentUploads'] = uploadsFor(`${teamId},${otherTeamId}`)
        })

        afterAll(() => {
            store.s3.destroy()
        })

        it.each([
            ['stores a file sent as declared, then answers present for it', (f: TestFile) => asked(f), true],
            [
                'refuses a file sent under the hash of other bytes of its size, and keeps answering upload',
                (f: TestFile) => asked(fileOf(Buffer.from(f.bytes).fill(0x41, f.bytes.length - 1))),
                false,
            ],
            [
                'refuses a file sent under a size it did not declare, and keeps answering upload',
                (f: TestFile) => ({ files: [{ sha256: f.sha256, size: f.bytes.length + 1 }] }),
                false,
            ],
        ])('%s', async (_name, declare, stored) => {
            const f = pdf()
            const declared = declare(f)

            const first = await requestUploads(teamId, declared)
            expect(first.status).toBe(200)
            expect(first.body.files).toEqual([
                expect.objectContaining({ sha256: declared.files[0].sha256, status: 'upload' }),
            ])
            expect(Date.parse(first.body.files[0].url_expires_at)).toBeGreaterThan(Date.now())

            const putStatus = await putBytesWithoutSignedContentLength(first.body.files[0], f.bytes)
            const again = await requestUploads(teamId, declared)

            expect(again.status).toBe(200)
            if (stored) {
                expect(putStatus).toBe(200)
                expect(again.body.files).toEqual([
                    { sha256: f.sha256, status: 'present', expires_at: expect.any(String) },
                ])
                expect(Date.parse(again.body.files[0].expires_at)).toBeGreaterThan(Date.now())
            } else {
                expect(putStatus).toBeGreaterThanOrEqual(400)
                expect(statusesOf(again)).toEqual(['upload'])
            }
        })

        it("answers upload to another team for a file only this team stored, and stores that team's own copy", async () => {
            const f = pdf()
            const [slot] = (await requestUploads(teamId, asked(f))).body.files
            expect(await putBytesWithoutSignedContentLength(slot, f.bytes)).toBe(200)

            const other = await requestUploads(otherTeamId, asked(f))

            expect(other.status).toBe(200)
            expect(statusesOf(other)).toEqual(['upload'])
            expect(await putBytesWithoutSignedContentLength(other.body.files[0], f.bytes)).toBe(200)
            expect(statusesOf(await requestUploads(otherTeamId, asked(f)))).toEqual(['present'])
        })

        it('refuses a team that is not on the allowlist before reading its files', async () => {
            const offTheList = await createTeam(hub.postgres, team.organization_id)

            const res = await requestUploads(offTheList, { files: [] })

            expect(res.status).toBe(400)
            expect(res.body).toEqual({ error: 'field_not_accepted' })
        })

        it.each([
            ['no files', { files: [] }],
            ['more than 10 files', sized(...Array(11).fill(1))],
            ['a hash that is not 64 lowercase hex characters', { files: [{ sha256: 'A'.repeat(64), size: 1 }] }],
            ['a size of zero', sized(0)],
            ['a size that is not a whole number', sized(1.5)],
            [
                'one hash listed with two sizes',
                { files: [1_000_000, 1].map((size) => ({ sha256: 'a'.repeat(64), size })) },
            ],
        ])('refuses a request with %s', async (_name, body) => {
            const res = await requestUploads(teamId, body)

            expect(res.status).toBe(400)
            expect(res.body.error).toBe('invalid_request')
        })

        const LARGEST_FILE_IN_ONE_MESSAGE = 29_182_875
        it.each([
            ['one file at the largest size that fits', [LARGEST_FILE_IN_ONE_MESSAGE], null],
            ['one file a byte over it', [LARGEST_FILE_IN_ONE_MESSAGE + 1], 0],
            ['two files that only fit apart', [10_000_000, 20_000_000], 1],
        ])('answers %s', async (_name, sizes, largestIndex) => {
            const body = sized(...sizes)

            const res = await requestUploads(teamId, body)

            if (largestIndex === null) {
                expect(res.status).toBe(200)
                expect(res.body.files).toEqual([expect.objectContaining({ status: 'upload' })])
            } else {
                expect(res.status).toBe(400)
                expect(res.body).toEqual({
                    error: 'message_too_large',
                    sha256: body.files[largestIndex].sha256,
                    message_bytes: expect.any(Number),
                    max_message_bytes: 40_000_000,
                })
                expect(res.body.message_bytes).toBeGreaterThan(40_000_000)
            }
        })

        it.each([
            ['a code send token', () => mintUploadTokenAsTheDjangoRouteDoes(teamId, { kind: 'code_send' })],
            ['a template send token', () => mintUploadTokenAsTheDjangoRouteDoes(teamId, {})],
            ["another team's token", () => mintUploadTokenAsTheDjangoRouteDoes(otherTeamId)],
            [
                'a token signed with another key',
                () => mintUploadTokenAsTheDjangoRouteDoes(teamId, undefined, 'wrong-key'),
            ],
        ])('refuses %s, and counts it as unauthorized', async (_name, token) => {
            const unauthorizedCount = async (): Promise<number> =>
                (
                    await (register.getSingleMetric('cdp_email_attachments_upload_requests_total') as Counter).get()
                ).values.find((v) => v.labels.outcome === 'unauthorized')?.value ?? 0
            const before = await unauthorizedCount()

            const res = await requestUploads(teamId, asked(pdf()), token())

            expect(res.status).toBe(401)
            expect(await unauthorizedCount()).toBe(before + 1)
        })

        it.each([
            ['answers upload with the idempotency Valkey as its counter', true, 200],
            ['answers delivery_unavailable without the idempotency Valkey', false, 503],
        ])('on a cdp-api built from its settings, %s', async (_name, withValkey, status) => {
            const builtApi = new CdpApi(
                { ...hub, CDP_EMAIL_ATTACHMENTS_TEAMS: `${teamId}` },
                { ...cdpDeps, idempotencyValkey: withValkey ? createIdempotencyValkeyPool(hub) : null },
                { hogQueue: createMockJobQueue(), hogflowQueue: createMockJobQueue() }
            )
            const builtApp = setupExpressApp()
            builtApp.use('/', builtApi.router())
            const builtServer = builtApp.listen(0, () => {})

            try {
                const res = await supertest(builtApp)
                    .post(`/api/projects/${teamId}/transactional_email/attachments/uploads`)
                    .set({ Authorization: `Bearer ${mintUploadTokenAsTheDjangoRouteDoes(teamId)}` })
                    .send(asked(pdf()))

                expect(res.status).toBe(status)
            } finally {
                builtServer.close()
            }
        })

        it('lets a request that fits through while larger requests at the same time are refused', async () => {
            const uploads = uploadsFor(`${teamId}`, { maxBytesPerTeamDay: 100 })
            const request = (size: number) => uploads.prepare(teamId, sized(size))
            expect((await request(90)).status).toBe(200)

            const answers = await Promise.all([
                ...Array.from({ length: 25 }, () => request(20)),
                request(5),
                ...Array.from({ length: 25 }, () => request(20)),
            ])

            expect(answers.map((answer) => answer.status)).toEqual([
                ...Array(25).fill(429),
                200,
                ...Array(25).fill(429),
            ])
        })

        it('refuses a team past its daily upload bytes, not another team, and counts neither present files nor refused requests', async () => {
            api['attachmentUploads'] = uploadsFor(`${teamId},${otherTeamId}`, { maxBytesPerTeamDay: 100 })
            const stored = pdf()
            const [slot] = (await requestUploads(teamId, asked(stored))).body.files
            expect(await putBytesWithoutSignedContentLength(slot, stored.bytes)).toBe(200)

            const presentAgain = await requestUploads(teamId, asked(stored, pdf()))
            const overTheCap = await requestUploads(teamId, asked(pdf(), pdf()))
            const smallAfterRefusal = await requestUploads(teamId, asked(fileOf(Buffer.from('ten bytes!'))))
            const otherTeam = await requestUploads(otherTeamId, asked(pdf(), pdf()))

            expect(presentAgain.status).toBe(200)
            expect(presentAgain.body.files.map((f: { status: string }) => f.status)).toEqual(['present', 'upload'])
            expect(overTheCap.status).toBe(429)
            expect(overTheCap.body).toEqual({ error: 'upload_quota_exceeded', max_bytes_per_day: 100 })
            expect(smallAfterRefusal.status).toBe(200)
            expect(otherTeam.status).toBe(200)
        })

        it.each([
            ['no attachment store is configured', () => uploadsFor(`${teamId}`, { attachmentStore: null })],
            [
                'the attachment store does not answer',
                () =>
                    uploadsFor(`${teamId}`, {
                        attachmentStore: buildAttachmentStore({
                            ...getDefaultCdpConfig(),
                            CDP_EMAIL_ATTACHMENTS_S3_ENDPOINT: 'http://127.0.0.1:9',
                            CDP_EMAIL_ATTACHMENTS_S3_TIMEOUT_MS: 1_000,
                        }),
                    }),
            ],
            ['no upload counter is configured', () => uploadsFor(`${teamId}`, { counter: null })],
            [
                'the upload counter does not answer',
                () =>
                    uploadsFor(`${teamId}`, {
                        counter: createIdempotencyValkeyPool({
                            ...hub,
                            CDP_IDEMPOTENCY_VALKEY_HOST: '127.0.0.1',
                            CDP_IDEMPOTENCY_VALKEY_PORT: 9,
                        }),
                    }),
            ],
        ])('answers 503 delivery_unavailable when %s', async (_name, uploads) => {
            api['attachmentUploads'] = uploads()

            const res = await requestUploads(teamId, asked(pdf()))

            expect(res.status).toBe(503)
            expect(res.body).toEqual({ error: 'delivery_unavailable' })
        })
    })
})
