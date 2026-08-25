// Serial: resets shared Postgres and relies on the reset-created default team.
import { createMockJobQueue } from '../../tests/helpers/mocks/job-queue.mock'
import { mockFetch } from '../../tests/helpers/mocks/request.mock'

import { Server } from 'http'
import jwt from 'jsonwebtoken'
import supertest from 'supertest'
import express from 'ultimate-express'

import { HogFlow } from '~/cdp/schema/hogflow'
import { PosthogJwtAudience } from '~/cdp/utils/jwt-utils'
import { ScopedServiceJwt } from '~/cdp/utils/scoped-service-jwt'
import { setupExpressApp } from '~/common/api/router'
import { deleteKeysWithPrefix } from '~/common/redis/_tests/redis'
import { createRedisV2PoolFromConfig } from '~/common/redis/redis-v2'
import { closeHub, createHub } from '~/common/utils/db/hub'
import { parseJSON } from '~/common/utils/json-parse'
import { UUIDT } from '~/common/utils/utils'

import { createCdpConsumerDeps } from '../../tests/helpers/cdp'
import { forSnapshot } from '../../tests/helpers/snapshots'
import { createTeam, getFirstTeam, resetTestDatabase } from '../../tests/helpers/sql'
import { Hub, Team } from '../types'
import { FixtureHogFlowBuilder } from './_tests/builders/hogflow.builder'
import { HOG_EXAMPLES, HOG_FILTERS_EXAMPLES, HOG_INPUTS_EXAMPLES } from './_tests/examples'
import {
    insertHogFunction as _insertHogFunction,
    createHogFunction,
    insertHogFunctionTemplate,
    insertIntegration,
} from './_tests/fixtures'
import { insertHogFlow as _insertHogFlow } from './_tests/fixtures-hogflows'
import { CdpApi } from './cdp-api'
import { CdpConsumerBaseDeps } from './consumers/cdp-base.consumer'
import { posthogFilterOutPlugin } from './legacy-plugins/_transformations/posthog-filter-out-plugin/template'
import { BASE_REDIS_KEY, HogWatcherState } from './services/monitoring/hog-watcher.service'
import { compileHog } from './templates/compiler'
import { HogFunctionInvocationGlobals, HogFunctionType } from './types'

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
        api = new CdpApi(hub, cdpDeps, {
            hogQueue: createMockJobQueue(),
            hogflowQueue: createMockJobQueue(),
        })
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

    it('errors if missing values', async () => {
        const res = await supertest(app)
            .post(`/api/projects/${hogFunction.team_id}/hog_functions/${hogFunction.id}/invocations`)
            .send({})

        expect(res.status).toEqual(400)
        expect(res.body).toEqual({
            error: 'Missing event',
        })
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
            api['batchResolverProducer'] = {
                createJob: createJobMock,
                countInFlightJobs: jest.fn().mockResolvedValue({ count: 0, byAction: {}, positionUnknown: 0 }),
                rescheduleParkedJobs: jest.fn(),
                cancelJobs: jest.fn(),
                disconnect: jest.fn().mockResolvedValue(undefined),
            }

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

        it('resolves the audience from the posted snapshot, not the live trigger filters', async () => {
            // The snapshot was validated at confirm time - re-reading the trigger here would let an
            // edit racing the dispatch widen the send past what was previewed.
            const snapshotProperties = [{ key: 'email', type: 'person', value: 'a', operator: 'icontains' }]

            const createJobMock = jest.fn().mockResolvedValue('resolver-job-id')
            api['batchResolverProducer'] = {
                createJob: createJobMock,
                countInFlightJobs: jest.fn().mockResolvedValue({ count: 0, byAction: {}, positionUnknown: 0 }),
                rescheduleParkedJobs: jest.fn(),
                cancelJobs: jest.fn(),
                disconnect: jest.fn().mockResolvedValue(undefined),
            }

            try {
                const res = await supertest(app)
                    .post(
                        `/api/projects/${batchHogFlow.team_id}/hog_flows/${batchHogFlow.id}/batch_invocations/job-791`
                    )
                    .send({ filters: { properties: snapshotProperties } })

                expect(res.status).toEqual(200)
                const arg = createJobMock.mock.calls[0][0]
                const state = parseJSON((arg.state as Buffer).toString('utf-8')) as Record<string, any>
                expect(state.filters.properties).toEqual(snapshotProperties)
                expect(state.filters.properties).not.toEqual((batchHogFlow as any).trigger.filters.properties)
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
            api['batchResolverProducer'] = {
                createJob: createJobMock,
                countInFlightJobs: jest.fn().mockResolvedValue({ count: 0, byAction: {}, positionUnknown: 0 }),
                rescheduleParkedJobs: jest.fn(),
                cancelJobs: jest.fn(),
                disconnect: jest.fn().mockResolvedValue(undefined),
            }

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
            api['batchResolverProducer'] = {
                createJob: createJobMock,
                countInFlightJobs: jest.fn().mockResolvedValue({ count: 0, byAction: {}, positionUnknown: 0 }),
                rescheduleParkedJobs: jest.fn(),
                cancelJobs: jest.fn(),
                disconnect: jest.fn().mockResolvedValue(undefined),
            }

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
            api['batchResolverProducer'] = {
                createJob: jest.fn(),
                disconnect: jest.fn(),
                countInFlightJobs: mockCountInFlightJobs,
                rescheduleParkedJobs: jest.fn(),
                cancelJobs: jest.fn(),
            }

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
            api['batchResolverProducer'] = {
                createJob: jest.fn(),
                disconnect: jest.fn(),
                countInFlightJobs: jest.fn(),
                rescheduleParkedJobs: mockRescheduleParkedJobs,
                cancelJobs: jest.fn(),
            }

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
            api['batchResolverProducer'] = {
                createJob: jest.fn(),
                disconnect: jest.fn(),
                countInFlightJobs: jest.fn(),
                rescheduleParkedJobs: jest.fn(),
                cancelJobs: mockCancelJobs,
            }
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
            api['batchResolverProducer'] = {
                createJob: jest.fn(),
                disconnect: jest.fn(),
                countInFlightJobs: jest.fn(),
                rescheduleParkedJobs: jest.fn(),
                cancelJobs: mockCancelJobs,
            }
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
                    })
                )
        })

        afterEach(() => {
            emailSpy.mockRestore()
        })

        it('sends the email inline via EmailService instead of routing to the email queue', async () => {
            const res = await supertest(app).post(`/api/projects/${team.id}/hog_flows/${hogFlowId}/invocations`).send({
                globals,
                configuration: {},
                current_action_id: 'email_1',
            })

            expect(res.status).toBe(200)
            expect(res.body.status).toBe('success')
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
})
