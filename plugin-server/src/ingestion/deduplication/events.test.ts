import { Message } from 'node-rdkafka'

import { IncomingEvent, PipelineEvent } from '~/types'

import { deduplicateEvents } from './events'
import * as metrics from './metrics'
import { DeduplicationRedis } from './redis-client'

// Mock the metrics
jest.mock('./metrics', () => ({
    duplicateBreakdownTotal: {
        inc: jest.fn(),
    },
}))

describe('deduplicateEvents', () => {
    let deduplicationRedis: DeduplicationRedis

    beforeEach(() => {
        // Mock DeduplicationRedis
        deduplicationRedis = {
            deduplicate: jest.fn(),
            deduplicateIds: jest.fn(),
        } as unknown as DeduplicationRedis

        // Clear all metrics mocks
        jest.clearAllMocks()
    })

    it('should call redis deduplicate with the correct hashed keys and publish metrics for duplicates', async () => {
        const messages = [
            {
                message: {} as unknown as Message,
                event: {
                    uuid: '1',
                    event: 'test',
                    distinct_id: 'test',
                    timestamp: '2021-01-01',
                    token: 'token',
                    team_id: 123,
                    properties: { $lib: 'web' },
                } as unknown as PipelineEvent,
            },
            {
                message: {} as unknown as Message,
                event: {
                    uuid: '2',
                    event: 'test',
                    distinct_id: 'test',
                    timestamp: '2021-01-03',
                    token: 'token',
                    team_id: 456,
                    properties: { $lib: 'python' },
                } as unknown as PipelineEvent,
            },
        ]

        // Mock deduplicateIds to return duplicates
        const duplicateKeys = new Set([
            '7ebcf011d2a6c17c9405fb2da91cba540aceab53ca59e562f49eacf6fd47996d',
            '7bfa9b827deb2126be762b189062579f0f962c169d25d4f002341c2679f4502b',
        ])
        deduplicationRedis.deduplicateIds = jest.fn().mockResolvedValue({
            duplicates: duplicateKeys,
            processed: 2,
        })

        await deduplicateEvents(deduplicationRedis, messages)

        expect(deduplicationRedis.deduplicateIds).toHaveBeenCalledWith({
            keys: [
                '7ebcf011d2a6c17c9405fb2da91cba540aceab53ca59e562f49eacf6fd47996d',
                '7bfa9b827deb2126be762b189062579f0f962c169d25d4f002341c2679f4502b',
            ],
        })
        expect(deduplicationRedis.deduplicate).not.toHaveBeenCalled()

        // Verify metrics were published with correct counts
        expect(metrics.duplicateBreakdownTotal.inc).toHaveBeenCalledTimes(2)
        expect(metrics.duplicateBreakdownTotal.inc).toHaveBeenCalledWith(
            {
                source: 'web',
            },
            1
        )
        expect(metrics.duplicateBreakdownTotal.inc).toHaveBeenCalledWith(
            {
                source: 'python',
            },
            1
        )
    })

    it('should resolve same event to same key and not publish metrics when no duplicates', async () => {
        const messages = [
            {
                message: {} as unknown as Message,
                event: {
                    uuid: '1',
                    event: 'test',
                    distinct_id: 'test',
                    timestamp: '2021-01-01',
                    token: 'token',
                    team_id: 123,
                    properties: { $lib: 'web' },
                } as unknown as PipelineEvent,
            },
            {
                message: {} as unknown as Message,
                event: {
                    uuid: '1',
                    event: 'test',
                    distinct_id: 'test',
                    timestamp: '2021-01-01',
                    token: 'token',
                    team_id: 123,
                    properties: { $lib: 'web' },
                } as unknown as PipelineEvent,
            },
        ]

        // Mock deduplicateIds to return no duplicates
        deduplicationRedis.deduplicateIds = jest.fn().mockResolvedValue({
            duplicates: new Set(),
            processed: 1,
        })

        await deduplicateEvents(deduplicationRedis, messages)

        expect(deduplicationRedis.deduplicateIds).toHaveBeenCalledWith({
            keys: ['7ebcf011d2a6c17c9405fb2da91cba540aceab53ca59e562f49eacf6fd47996d'],
        })
        expect(deduplicationRedis.deduplicate).not.toHaveBeenCalled()

        // Verify no metrics were published when no duplicates found
        expect(metrics.duplicateBreakdownTotal.inc).not.toHaveBeenCalled()
    })

    it('should handle empty messages', async () => {
        const messages: IncomingEvent[] = []
        await deduplicateEvents(deduplicationRedis, messages)
        expect(deduplicationRedis.deduplicateIds).not.toHaveBeenCalled()
        expect(deduplicationRedis.deduplicate).not.toHaveBeenCalled()
        expect(metrics.duplicateBreakdownTotal.inc).not.toHaveBeenCalled()
    })
})
