import { mockFetch } from '~/tests/helpers/mocks/request.mock'

import { Message } from 'node-rdkafka'

import { defaultConfig } from '../../../config/config'
import { PluginsServerConfig } from '../../../types'
import { parseJSON } from '../../../utils/json-parse'
import {
    WarpstreamFetchTester,
    cdpSeekBatchLatencyMs,
    cdpSeekBatchTotalLatencyMs,
    cdpSeekLatencyMs,
    cdpSeekResult,
    cdpSeekTotalLatencyMs,
} from './warpstream-fetch-tester'

jest.mock('../../../kafka/config', () => ({
    getKafkaConfigFromEnv: () => ({
        'sasl.username': 'user',
        'sasl.password': 'pass',
    }),
}))

function makeMessage(topic: string, partition: number, offset: number): Message {
    return { topic, partition, offset, value: Buffer.from('test'), size: 4, timestamp: Date.now() } as Message
}

function makeMessages(count: number, offset = 100): Message[] {
    return Array.from({ length: count }, (_, i) => makeMessage('test_topic', i % 4, offset + i))
}

describe('WarpstreamFetchTester', () => {
    let tester: WarpstreamFetchTester
    let config: PluginsServerConfig

    beforeEach(() => {
        config = {
            ...defaultConfig,
            CDP_CYCLOTRON_WARPSTREAM_HTTP_URL: 'http://warpstream:8080',
            CDP_CYCLOTRON_TEST_SEEK_MAX_OFFSET: 50,
            CDP_CYCLOTRON_TEST_FETCH_INDIVIDUAL_COUNT: 0,
            CDP_CYCLOTRON_TEST_FETCH_BATCH_COUNT: 0,
            CDP_CYCLOTRON_TEST_FETCH_BATCH_SIZE: 10,
        }
        tester = new WarpstreamFetchTester(config)
        tester.start()

        mockFetch.mockClear()
        cdpSeekLatencyMs.reset()
        cdpSeekTotalLatencyMs.reset()
        cdpSeekBatchLatencyMs.reset()
        cdpSeekBatchTotalLatencyMs.reset()
        cdpSeekResult.reset()
    })

    it('should do nothing when both counts are 0', async () => {
        await tester.maybeMeasureFetchLatency(makeMessages(100))
        expect(mockFetch).not.toHaveBeenCalled()
    })

    it('should do nothing when all messages have offset 0', async () => {
        config.CDP_CYCLOTRON_TEST_FETCH_INDIVIDUAL_COUNT = 10
        const messages = Array.from({ length: 5 }, () => makeMessage('topic', 0, 0))

        await tester.maybeMeasureFetchLatency(messages)
        expect(mockFetch).not.toHaveBeenCalled()
    })

    it('should fire individual fetches to single-record endpoint', async () => {
        config.CDP_CYCLOTRON_TEST_FETCH_INDIVIDUAL_COUNT = 3
        const messages = makeMessages(3)

        await tester.maybeMeasureFetchLatency(messages)

        expect(mockFetch).toHaveBeenCalledTimes(3)
        for (const call of mockFetch.mock.calls) {
            expect(call[0]).toMatch(/\/v1\/kafka\/topics\/test_topic\/partitions\/\d+\/records\/\d+/)
            expect(call[1].headers['Authorization']).toBe('Basic ' + Buffer.from('user:pass').toString('base64'))
        }

        const result = await cdpSeekResult.get()
        const successes = result.values.filter((v) => v.labels.result === 'success' && v.labels.method === 'individual')
        expect(successes.reduce((sum, v) => sum + v.value, 0)).toBe(3)
    })

    it('should fire batch fetches to batch endpoint', async () => {
        config.CDP_CYCLOTRON_TEST_FETCH_BATCH_COUNT = 2
        config.CDP_CYCLOTRON_TEST_FETCH_BATCH_SIZE = 5
        const messages = makeMessages(20)

        await tester.maybeMeasureFetchLatency(messages)

        expect(mockFetch).toHaveBeenCalledTimes(2)
        for (const call of mockFetch.mock.calls) {
            expect(call[0]).toBe('http://warpstream:8080/v1/kafka/fetch')
            expect(call[1].method).toBe('POST')
            expect(call[1].headers['Content-Type']).toBe('application/json')

            const body = parseJSON(call[1].body)
            expect(body.topics).toBeDefined()
            const totalPartitions = body.topics.reduce((sum: number, t: any) => sum + t.partitions.length, 0)
            expect(totalPartitions).toBe(5)
        }

        const result = await cdpSeekResult.get()
        const successes = result.values.filter((v) => v.labels.result === 'success' && v.labels.method === 'batch')
        expect(successes.reduce((sum, v) => sum + v.value, 0)).toBe(2)
    })

    it('should run both strategies concurrently when both configured', async () => {
        config.CDP_CYCLOTRON_TEST_FETCH_INDIVIDUAL_COUNT = 5
        config.CDP_CYCLOTRON_TEST_FETCH_BATCH_COUNT = 2
        config.CDP_CYCLOTRON_TEST_FETCH_BATCH_SIZE = 5
        const messages = makeMessages(20)

        await tester.maybeMeasureFetchLatency(messages)

        const individualCalls = mockFetch.mock.calls.filter((c) => !c[0].includes('/v1/kafka/fetch'))
        const batchCalls = mockFetch.mock.calls.filter((c) => c[0] === 'http://warpstream:8080/v1/kafka/fetch')

        expect(individualCalls).toHaveLength(5)
        expect(batchCalls).toHaveLength(2)
    })

    it('should sample down when more targets than configured count', async () => {
        config.CDP_CYCLOTRON_TEST_FETCH_INDIVIDUAL_COUNT = 3
        const messages = makeMessages(100)

        await tester.maybeMeasureFetchLatency(messages)
        expect(mockFetch).toHaveBeenCalledTimes(3)
    })

    it('should record error metrics on non-2xx responses', async () => {
        config.CDP_CYCLOTRON_TEST_FETCH_INDIVIDUAL_COUNT = 2
        mockFetch.mockResolvedValue({
            status: 500,
            headers: {},
            json: () => Promise.resolve({}),
            text: () => Promise.resolve('error'),
            dump: () => Promise.resolve(),
        })

        await tester.maybeMeasureFetchLatency(makeMessages(2))

        const result = await cdpSeekResult.get()
        const errors = result.values.filter((v) => v.labels.result === 'error' && v.labels.method === 'individual')
        expect(errors.reduce((sum, v) => sum + v.value, 0)).toBe(2)
    })

    it('should record error metrics on fetch exceptions', async () => {
        config.CDP_CYCLOTRON_TEST_FETCH_BATCH_COUNT = 1
        config.CDP_CYCLOTRON_TEST_FETCH_BATCH_SIZE = 3
        mockFetch.mockRejectedValue(new Error('connection refused'))

        await tester.maybeMeasureFetchLatency(makeMessages(3))

        const result = await cdpSeekResult.get()
        const errors = result.values.filter((v) => v.labels.result === 'error' && v.labels.method === 'batch')
        expect(errors.reduce((sum, v) => sum + v.value, 0)).toBe(1)
    })
})
