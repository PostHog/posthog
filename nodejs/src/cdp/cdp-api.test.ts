import { createMockJobQueue } from '../../tests/helpers/mocks/job-queue.mock'
import { mockFetch } from '../../tests/helpers/mocks/request.mock'

import { Server } from 'http'
import supertest from 'supertest'
import express from 'ultimate-express'

import { HogFlow } from '~/cdp/schema/hogflow'
import { setupExpressApp } from '~/common/api/router'
import { deleteKeysWithPrefix } from '~/common/redis/_tests/redis'
import { createRedisV2PoolFromConfig } from '~/common/redis/redis-v2'
import { closeHub, createHub } from '~/common/utils/db/hub'
import { parseJSON } from '~/common/utils/json-parse'
import { UUIDT } from '~/common/utils/utils'

import { createCdpConsumerDeps } from '../../tests/helpers/cdp'
import { forSnapshot } from '../../tests/helpers/snapshots'
import { getFirstTeam, resetTestDatabase } from '../../tests/helpers/sql'
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
                    "$transformations_succeeded": [
                      "Filter Out Plugin (<REPLACED-UUID-1>)",
                    ],
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

    // The test panel POSTs to /hog_flows/:id/invocations and runs the executor in-process —
    // it never enqueues into cyclotron. If the executor routes an email action onto the
    // dedicated email queue, nothing services that job and the workflow stalls on a
    // "Workflow will pause until …" log. The handler forces `sendEmailsInline: true` so the
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
                .spyOn(api['hogExecutor']['emailService'], 'executeSendEmail')
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
                        emailAssets: [],
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
