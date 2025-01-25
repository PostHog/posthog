import '../helpers/mocks/producer.mock'

import express from 'express'
import supertest from 'supertest'

import { CdpApi } from '../../src/cdp/cdp-api'
import { CdpInternalEventsConsumer } from '../../src/cdp/consumers/cdp-internal-event.consumer'
import { HogFunctionInvocationGlobals, HogFunctionType } from '../../src/cdp/types'
import { Hub, Team } from '../../src/types'
import { closeHub, createHub } from '../../src/utils/db/hub'
import { getFirstTeam, resetTestDatabase } from '../helpers/sql'
import { HOG_EXAMPLES, HOG_FILTERS_EXAMPLES, HOG_INPUTS_EXAMPLES } from './examples'
import { insertHogFunction as _insertHogFunction } from './fixtures'

const mockConsumer = {
    on: jest.fn(),
    commitSync: jest.fn(),
    commit: jest.fn(),
    queryWatermarkOffsets: jest.fn(),
    committed: jest.fn(),
    assignments: jest.fn(),
    isConnected: jest.fn(() => true),
    getMetadata: jest.fn(),
}

jest.mock('../../src/kafka/batch-consumer', () => {
    return {
        startBatchConsumer: jest.fn(() =>
            Promise.resolve({
                join: () => ({
                    finally: jest.fn(),
                }),
                stop: jest.fn(),
                consumer: mockConsumer,
            })
        ),
    }
})

jest.mock('../../src/utils/fetch', () => {
    return {
        trackedFetch: jest.fn(() =>
            Promise.resolve({
                status: 200,
                text: () => Promise.resolve(JSON.stringify({ success: true })),
                json: () => Promise.resolve({ success: true }),
            })
        ),
    }
})

const mockFetch: jest.Mock = require('../../src/utils/fetch').trackedFetch

jest.setTimeout(1000)

describe('CDP API', () => {
    let processor: CdpInternalEventsConsumer
    let hub: Hub
    let team: Team

    const insertHogFunction = async (hogFunction: Partial<HogFunctionType>) => {
        const item = await _insertHogFunction(hub.postgres, team.id, hogFunction)
        // Trigger the reload that django would do
        await processor.hogFunctionManager.reloadAllHogFunctions()
        return item
    }

    beforeEach(async () => {
        await resetTestDatabase()
        hub = await createHub()
        team = await getFirstTeam(hub)

        hub.CDP_GOOGLE_ADWORDS_DEVELOPER_TOKEN = 'ADWORDS_TOKEN'

        processor = new CdpInternalEventsConsumer(hub)

        await processor.start()

        mockFetch.mockClear()
    })

    afterEach(async () => {
        jest.setTimeout(10000)
        await processor.stop()
        await closeHub(hub)
    })

    afterAll(() => {
        jest.useRealTimers()
    })

    describe('API invocation', () => {
        let app: express.Express
        let hogFunction: HogFunctionType

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

        beforeEach(async () => {
            app = express()
            app.use(express.json())
            const api = new CdpApi(hub, processor)
            app.use('/', api.router())

            hogFunction = await insertHogFunction({
                ...HOG_EXAMPLES.simple_fetch,
                ...HOG_INPUTS_EXAMPLES.simple_fetch,
                ...HOG_FILTERS_EXAMPLES.no_filters,
            })
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

        it('can invoke a function via the API with mocks', async () => {
            const res = await supertest(app)
                .post(`/api/projects/${hogFunction.team_id}/hog_functions/${hogFunction.id}/invocations`)
                .send({ globals, mock_async_functions: true })

            expect(res.status).toEqual(200)
            console.log(res.body.logs[3].message)
            expect(res.body).toMatchObject({
                errors: [],
                logs: [
                    {
                        level: 'debug',
                        message: 'Executing function',
                    },
                    {
                        level: 'debug',
                        message:
                            "Suspending function due to async function call 'fetch'. Payload: 2110 bytes. Event: b3a1fe86-b10c-43cc-acaf-d208977608d0",
                    },
                    {
                        level: 'info',
                        message: "Async function 'fetch' was mocked with arguments:",
                    },
                    {
                        level: 'info',
                        message: expect.stringContaining('fetch({'),
                    },
                    {
                        level: 'debug',
                        message: 'Resuming function',
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

        it('can invoke a function via the API with real fetch', async () => {
            mockFetch.mockImplementationOnce(() =>
                Promise.resolve({
                    status: 201,
                    text: () => Promise.resolve(JSON.stringify({ real: true })),
                    headers: new Headers({ 'Content-Type': 'application/json' }),
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
                        level: 'debug',
                        message: 'Executing function',
                    },
                    {
                        level: 'debug',
                        message:
                            "Suspending function due to async function call 'fetch'. Payload: 2110 bytes. Event: b3a1fe86-b10c-43cc-acaf-d208977608d0",
                    },
                    {
                        level: 'debug',
                        message: 'Resuming function',
                    },
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

        it('includes enriched values in the request', async () => {
            mockFetch.mockImplementationOnce(() => {
                return Promise.resolve({
                    status: 201,
                    text: () => Promise.resolve(JSON.stringify({ real: true })),
                    headers: new Headers({ 'Content-Type': 'application/json' }),
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
                        level: 'debug',
                        message: 'Executing function',
                    },
                    {
                        level: 'debug',
                        message:
                            "Suspending function due to async function call 'fetch'. Payload: 2108 bytes. Event: b3a1fe86-b10c-43cc-acaf-d208977608d0",
                    },
                    {
                        level: 'debug',
                        message: 'Resuming function',
                    },
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
                        level: 'debug',
                        message: 'Executing function',
                    },
                    {
                        level: 'debug',
                        message:
                            "Suspending function due to async function call 'fetch'. Payload: 2108 bytes. Event: b3a1fe86-b10c-43cc-acaf-d208977608d0",
                    },
                    {
                        level: 'info',
                        message: "Async function 'fetch' was mocked with arguments:",
                    },
                    {
                        level: 'info',
                        message: expect.not.stringContaining('developer-token'),
                    },
                    {
                        level: 'debug',
                        message: 'Resuming function',
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

            const minimalLogs = res.body.logs.map((log) => ({
                level: log.level,
                message: log.message,
            }))

            expect(minimalLogs).toMatchObject([
                { level: 'info', message: 'Mapping trigger not matching filters was ignored.' },
                {
                    level: 'error',
                    message:
                        'Error filtering event b3a1fe86-b10c-43cc-acaf-d208977608d0: Invalid HogQL bytecode, stack is empty, can not pop',
                },
                { level: 'debug', message: 'Executing function' },
                {
                    level: 'debug',
                    message:
                        "Suspending function due to async function call 'fetch'. Payload: 2110 bytes. Event: b3a1fe86-b10c-43cc-acaf-d208977608d0",
                },
                {
                    level: 'info',
                    message: "Async function 'fetch' was mocked with arguments:",
                },
                {
                    level: 'info',
                    message: expect.stringContaining('fetch({'),
                },
                { level: 'debug', message: 'Resuming function' },
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
            expect(res.body).toMatchObject({
                logs: [
                    {
                        level: 'debug',
                        message: 'Executing function',
                    },
                    {
                        level: 'debug',
                        message:
                            "Suspending function due to async function call 'fetch'. Payload: 2108 bytes. Event: b3a1fe86-b10c-43cc-acaf-d208977608d0",
                    },
                    {
                        level: 'info',
                        message: "Async function 'fetch' was mocked with arguments:",
                    },
                    {
                        level: 'info',
                        message: expect.not.stringContaining('developer-token'),
                    },
                    {
                        level: 'debug',
                        message: 'Resuming function',
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

            const minimalLogs = res.body.logs.map((log) => ({
                level: log.level,
                message: log.message,
            }))

            expect(minimalLogs).toMatchObject([
                { level: 'info', message: 'Mapping trigger not matching filters was ignored.' },
                {
                    level: 'error',
                    message:
                        'Error filtering event b3a1fe86-b10c-43cc-acaf-d208977608d0: Invalid HogQL bytecode, stack is empty, can not pop',
                },
                { level: 'debug', message: 'Executing function' },
                {
                    level: 'debug',
                    message:
                        "Suspending function due to async function call 'fetch'. Payload: 2110 bytes. Event: b3a1fe86-b10c-43cc-acaf-d208977608d0",
                },
                {
                    level: 'info',
                    message: "Async function 'fetch' was mocked with arguments:",
                },
                {
                    level: 'info',
                    message: expect.stringContaining('fetch({'),
                },
                { level: 'debug', message: 'Resuming function' },
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
    })
})
