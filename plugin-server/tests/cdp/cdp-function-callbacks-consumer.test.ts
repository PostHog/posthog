import express from 'express'
import supertest from 'supertest'

import { CdpApi } from '../../src/cdp/cdp-api'
import { CdpFunctionCallbackConsumer } from '../../src/cdp/cdp-consumers'
import { HogFunctionType } from '../../src/cdp/types'
import { Hub, Team } from '../../src/types'
import { createHub } from '../../src/utils/db/hub'
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

        processor = new CdpFunctionCallbackConsumer(hub)

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

    describe('API invocation', () => {
        let app: express.Express
        let hogFunction: HogFunctionType

        const globals = {
            event: {
                uuid: 'b3a1fe86-b10c-43cc-acaf-d208977608d0',
                name: '$pageview',
                properties: {
                    $lib_version: '1.0.0',
                },
            },
            groups: {},
            person: {
                uuid: 'b3a1fe86-b10c-43cc-acaf-d208977608d0',
                distinct_ids: ['b3a1fe86-b10c-43cc-acaf-d208977608d0'],
                properties: {
                    email: 'test@posthog.com',
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
            expect(res.body).toMatchObject({
                status: 'success',
                error: 'undefined',
                logs: [
                    {
                        level: 'debug',
                        message: 'Executing function',
                    },
                    {
                        level: 'debug',
                        message: "Suspending function due to async function call 'fetch'. Payload: 1639 bytes",
                    },
                    {
                        level: 'info',
                        message: "Async function 'fetch' was mocked with arguments:",
                    },
                    {
                        level: 'info',
                        message: expect.stringContaining('fetch("https://example.com/posthog-webhook",'),
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
                })
            )
            const res = await supertest(app)
                .post(`/api/projects/${hogFunction.team_id}/hog_functions/${hogFunction.id}/invocations`)
                .send({ globals, mock_async_functions: false })

            expect(res.status).toEqual(200)
            expect(res.body).toMatchObject({
                status: 'success',
                error: 'undefined',
                logs: [
                    {
                        level: 'debug',
                        message: 'Executing function',
                    },
                    {
                        level: 'debug',
                        message: "Suspending function due to async function call 'fetch'. Payload: 1639 bytes",
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
    })
})
