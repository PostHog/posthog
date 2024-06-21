import express from 'express'
import supertest from 'supertest'

import { CdpFunctionCallbackConsumer } from '../../src/cdp/cdp-consumers'
import { HogFunctionType } from '../../src/cdp/types'
import { defaultConfig } from '../../src/config/config'
import { Hub, PluginsServerConfig, Team } from '../../src/types'
import { createHub } from '../../src/utils/db/hub'
import { getFirstTeam, resetTestDatabase } from '../helpers/sql'
import { HOG_EXAMPLES, HOG_FILTERS_EXAMPLES, HOG_INPUTS_EXAMPLES } from './examples'
import { insertHogFunction as _insertHogFunction } from './fixtures'

const config: PluginsServerConfig = {
    ...defaultConfig,
}

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

jest.mock('../../src/utils/db/kafka-producer-wrapper', () => {
    const mockKafkaProducer = {
        producer: {
            connect: jest.fn(),
        },
        disconnect: jest.fn(),
        produce: jest.fn(),
    }
    return {
        KafkaProducerWrapper: jest.fn(() => mockKafkaProducer),
    }
})

const mockFetch: jest.Mock = require('../../src/utils/fetch').trackedFetch

jest.setTimeout(1000)

describe('CDP Processed Events Consuner', () => {
    let processor: CdpFunctionCallbackConsumer
    let hub: Hub
    let closeHub: () => Promise<void>
    let team: Team

    const insertHogFunction = async (hogFunction: Partial<HogFunctionType>) => {
        const item = await _insertHogFunction(hub.postgres, team.id, hogFunction)
        // Trigger the reload that django would do
        await processor.hogFunctionManager.reloadAllHogFunctions()
        return item
    }

    beforeEach(async () => {
        await resetTestDatabase()
        ;[hub, closeHub] = await createHub()
        team = await getFirstTeam(hub)

        processor = new CdpFunctionCallbackConsumer(config, hub)
        await processor.start()

        mockFetch.mockClear()
    })

    afterEach(async () => {
        jest.setTimeout(10000)
        await processor.stop()
        await closeHub()
    })

    afterAll(() => {
        jest.useRealTimers()
    })

    // describe('general event processing', () => {
    //     /**
    //      * Tests here are somewhat expensive so should mostly simulate happy paths and the more e2e scenarios
    //      */
    //     it('can parse incoming messages correctly', async () => {
    //         await insertHogFunction({
    //             ...HOG_EXAMPLES.simple_fetch,
    //             ...HOG_INPUTS_EXAMPLES.simple_fetch,
    //             ...HOG_FILTERS_EXAMPLES.no_filters,
    //         })
    //         // Create a message that should be processed by this function
    //         // Run the function and check that it was executed
    //         await processor.handleEachBatch(
    //             [
    //                 createMessage(
    //                     createIncomingEvent(team.id, {
    //                         uuid: 'b3a1fe86-b10c-43cc-acaf-d208977608d0',
    //                         event: '$pageview',
    //                         properties: JSON.stringify({
    //                             $lib_version: '1.0.0',
    //                         }),
    //                     })
    //                 ),
    //             ],
    //             noop
    //         )

    //         expect(mockFetch).toHaveBeenCalledTimes(1)
    //         expect(mockFetch.mock.calls[0]).toMatchInlineSnapshot(`
    //             Array [
    //               "https://example.com/posthog-webhook",
    //               Object {
    //                 "body": "{
    //                 \\"event\\": {
    //                     \\"uuid\\": \\"b3a1fe86-b10c-43cc-acaf-d208977608d0\\",
    //                     \\"name\\": \\"$pageview\\",
    //                     \\"distinct_id\\": \\"distinct_id_1\\",
    //                     \\"properties\\": {
    //                         \\"$lib_version\\": \\"1.0.0\\",
    //                         \\"$elements_chain\\": \\"[]\\"
    //                     },
    //                     \\"timestamp\\": null,
    //                     \\"url\\": \\"http://localhost:8000/project/2/events/b3a1fe86-b10c-43cc-acaf-d208977608d0/null\\"
    //                 },
    //                 \\"groups\\": null,
    //                 \\"nested\\": {
    //                     \\"foo\\": \\"http://localhost:8000/project/2/events/b3a1fe86-b10c-43cc-acaf-d208977608d0/null\\"
    //                 },
    //                 \\"person\\": null,
    //                 \\"event_url\\": \\"http://localhost:8000/project/2/events/b3a1fe86-b10c-43cc-acaf-d208977608d0/null-test\\"
    //             }",
    //                 "headers": Object {
    //                   "version": "v=1.0.0",
    //                 },
    //                 "method": "POST",
    //                 "timeout": 10000,
    //               },
    //             ]
    //         `)
    //     })

    //     it('generates logs and produces them to kafka', async () => {
    //         await insertHogFunction({
    //             ...HOG_EXAMPLES.simple_fetch,
    //             ...HOG_INPUTS_EXAMPLES.simple_fetch,
    //             ...HOG_FILTERS_EXAMPLES.no_filters,
    //         })

    //         // Create a message that should be processed by this function
    //         // Run the function and check that it was executed
    //         await processor.handleEachBatch(
    //             [
    //                 createMessage(
    //                     createIncomingEvent(team.id, {
    //                         uuid: 'b3a1fe86-b10c-43cc-acaf-d208977608d0',
    //                         event: '$pageview',
    //                         properties: JSON.stringify({
    //                             $lib_version: '1.0.0',
    //                         }),
    //                     })
    //                 ),
    //             ],
    //             noop
    //         )

    //         expect(mockFetch).toHaveBeenCalledTimes(1)
    //         // Once for the async callback, twice for the logs
    //         expect(mockProducer.produce).toHaveBeenCalledTimes(3)

    //         expect(decodeKafkaMessage(mockProducer.produce.mock.calls[0][0])).toMatchObject({
    //             key: expect.any(String),
    //             topic: 'log_entries_test',
    //             value: {
    //                 instance_id: expect.any(String),
    //                 level: 'debug',
    //                 log_source: 'hog_function',
    //                 log_source_id: expect.any(String),
    //                 message: 'Executing function',
    //                 team_id: 2,
    //                 timestamp: expect.any(String),
    //             },
    //             waitForAck: true,
    //         })

    //         expect(decodeKafkaMessage(mockProducer.produce.mock.calls[1][0])).toMatchObject({
    //             topic: 'log_entries_test',
    //             value: {
    //                 log_source: 'hog_function',
    //                 message: "Suspending function due to async function call 'fetch'",
    //                 team_id: 2,
    //             },
    //         })

    //         expect(decodeKafkaMessage(mockProducer.produce.mock.calls[2][0])).toEqual({
    //             key: expect.any(String),
    //             topic: 'cdp_function_callbacks_test',
    //             value: {
    //                 id: expect.any(String),
    //                 globals: expect.objectContaining({
    //                     project: { id: 2, name: 'TEST PROJECT', url: 'http://localhost:8000/project/2' },
    //                     // We assume the rest is correct
    //                 }),
    //                 teamId: 2,
    //                 hogFunctionId: expect.any(String),
    //                 finished: false,
    //                 logs: [],
    //                 timings: [
    //                     {
    //                         kind: 'hog',
    //                         duration_ms: expect.any(Number),
    //                     },
    //                 ],
    //                 asyncFunctionRequest: {
    //                     name: 'fetch',
    //                     args: [
    //                         'https://example.com/posthog-webhook',
    //                         {
    //                             headers: { version: 'v=1.0.0' },
    //                             body: {
    //                                 event: {
    //                                     uuid: 'b3a1fe86-b10c-43cc-acaf-d208977608d0',
    //                                     name: '$pageview',
    //                                     distinct_id: 'distinct_id_1',
    //                                     properties: { $lib_version: '1.0.0', $elements_chain: '[]' },
    //                                     timestamp: null,
    //                                     url: 'http://localhost:8000/project/2/events/b3a1fe86-b10c-43cc-acaf-d208977608d0/null',
    //                                 },
    //                                 event_url:
    //                                     'http://localhost:8000/project/2/events/b3a1fe86-b10c-43cc-acaf-d208977608d0/null-test',
    //                                 groups: null,
    //                                 nested: {
    //                                     foo: 'http://localhost:8000/project/2/events/b3a1fe86-b10c-43cc-acaf-d208977608d0/null',
    //                                 },
    //                                 person: null,
    //                             },
    //                             method: 'POST',
    //                         },
    //                     ],
    //                     vmState: expect.any(Object),
    //                 },
    //                 asyncFunctionResponse: {
    //                     vmResponse: {
    //                         status: 200,
    //                         body: { success: true },
    //                     },
    //                     timings: [
    //                         {
    //                             kind: 'async_function',
    //                             duration_ms: expect.any(Number),
    //                         },
    //                     ],
    //                 },
    //             },
    //             waitForAck: true,
    //         })
    //     })
    // })

    describe('API invocation', () => {
        let app: express.Express
        let hogFunction: HogFunctionType

        const event = {
            uuid: 'b3a1fe86-b10c-43cc-acaf-d208977608d0',
            event: '$pageview',
            properties: {
                $lib_version: '1.0.0',
            },
        }

        beforeEach(async () => {
            app = express()
            app.use(express.json())
            processor.addApiRoutes(app)

            hogFunction = await insertHogFunction({
                ...HOG_EXAMPLES.simple_fetch,
                ...HOG_INPUTS_EXAMPLES.simple_fetch,
                ...HOG_FILTERS_EXAMPLES.no_filters,
            })
        })

        it('errors if missing hog function or team', async () => {
            const res = await supertest(app)
                .post(`/api/projects/${hogFunction.team_id}/hog_functions/missing/invocations`)
                .send({ event })

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
                .send({ event, mock_async_functions: true })

            expect(res.status).toEqual(200)
            expect(res.body).toMatchObject({
                status: 'success',
                error: 'undefined',
                logs: [
                    {
                        log_source: 'hog_function',
                        level: 'debug',
                        message: 'Executing function',
                    },
                    {
                        log_source: 'hog_function',
                        level: 'debug',
                        message: "Suspending function due to async function call 'fetch'",
                    },
                    {
                        log_source: 'hog_function',
                        level: 'info',
                        message: "Async function 'fetch' was mocked",
                    },
                    {
                        log_source: 'hog_function',
                        level: 'debug',
                        message: 'Resuming function',
                    },
                    {
                        log_source: 'hog_function',
                        level: 'info',
                        message: 'Fetch response:, {"status":200,"body":{}}',
                    },
                    {
                        log_source: 'hog_function',
                        level: 'debug',
                        message: expect.stringContaining('Function completed. Processing time'),
                    },
                ],
            })
        })

        it('can invoke a function via the API with real fetch', async () => {
            mockFetch.mockImplementationOnce(() =>
                Promise.resolve({
                    status: 201,
                    text: () => Promise.resolve(JSON.stringify({ real: true })),
                })
            )
            const res = await supertest(app)
                .post(`/api/projects/${hogFunction.team_id}/hog_functions/${hogFunction.id}/invocations`)
                .send({ event, mock_async_functions: false })

            expect(res.status).toEqual(200)
            expect(res.body).toMatchObject({
                status: 'success',
                error: 'undefined',
                logs: [
                    {
                        log_source: 'hog_function',
                        level: 'debug',
                        message: 'Executing function',
                    },
                    {
                        log_source: 'hog_function',
                        level: 'debug',
                        message: "Suspending function due to async function call 'fetch'",
                    },
                    {
                        log_source: 'hog_function',
                        level: 'debug',
                        message: 'Resuming function',
                    },
                    {
                        log_source: 'hog_function',
                        level: 'info',
                        message: 'Fetch response:, {"status":201,"body":{"real":true}}',
                    },
                    {
                        log_source: 'hog_function',
                        level: 'debug',
                        message: expect.stringContaining('Function completed. Processing time'),
                    },
                ],
            })
        })
    })
})
