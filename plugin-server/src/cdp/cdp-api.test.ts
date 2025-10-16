import '../../tests/helpers/mocks/producer.mock'
import { mockFetch } from '../../tests/helpers/mocks/request.mock'

import { Server } from 'http'
import supertest from 'supertest'
import express from 'ultimate-express'

import { setupExpressApp } from '~/api/router'

import { forSnapshot } from '../../tests/helpers/snapshots'
import { getFirstTeam, resetTestDatabase } from '../../tests/helpers/sql'
import { Hub, Team } from '../types'
import { closeHub, createHub } from '../utils/db/hub'
import { HOG_EXAMPLES, HOG_FILTERS_EXAMPLES, HOG_INPUTS_EXAMPLES } from './_tests/examples'
import { insertHogFunction as _insertHogFunction, createHogFunction } from './_tests/fixtures'
import { deleteKeysWithPrefix } from './_tests/redis'
import { CdpApi } from './cdp-api'
import { posthogFilterOutPlugin } from './legacy-plugins/_transformations/posthog-filter-out-plugin/template'
import { createCdpRedisPool } from './redis'
import { BASE_REDIS_KEY, HogWatcherState } from './services/monitoring/hog-watcher.service'
import { HogFunctionInvocationGlobals, HogFunctionType } from './types'

describe('CDP API', () => {
    let hub: Hub
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

    beforeAll(async () => {
        hub = await createHub({
            SITE_URL: 'http://localhost:8000',
        })
        hub.CDP_GOOGLE_ADWORDS_DEVELOPER_TOKEN = 'ADWORDS_TOKEN'
        team = await getFirstTeam(hub)

        api = new CdpApi(hub)
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

    it('errors if missing hog function or team', async () => {
        const res = await supertest(app)
            .post(`/api/projects/${hogFunction.team_id}/hog_functions/missing/invocations`)
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
            const redis = createCdpRedisPool(hub)
            await deleteKeysWithPrefix(redis, BASE_REDIS_KEY)
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
})
