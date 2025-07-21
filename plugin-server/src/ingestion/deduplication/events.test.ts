import { Message } from 'node-rdkafka'

import { IncomingEvent, PipelineEvent } from '~/types'

import { deduplicateEvents } from './events'
import { DeduplicationRedis } from './redis-client'

describe('deduplicateEvents', () => {
    let deduplicationRedis: DeduplicationRedis

    beforeEach(() => {
        // Mock DeduplicationRedis
        deduplicationRedis = {
            deduplicate: jest.fn(),
        } as unknown as DeduplicationRedis
    })

    it('should call redis deduplicate with the correct hashed keys', async () => {
        const messages = [
            {
                message: {} as unknown as Message,
                event: {
                    uuid: '1',
                    event: 'test',
                    distinct_id: 'test',
                    timestamp: '2021-01-01',
                    token: 'token',
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
                } as unknown as PipelineEvent,
            },
        ]

        await deduplicateEvents(deduplicationRedis, messages)

        expect(deduplicationRedis.deduplicate).toHaveBeenCalledWith({
            keys: [
                '7a184cabe9cce485b181a9b8113845fededc36f56d7d4eff4fbebca53abd55f7',
                'd0eafb964a9b3a603d44cea8376f5434e24fec80760e0bed1cd5b76ee5869796',
            ],
        })
    })

    it('should resolve same event to same key', async () => {
        const messages = [
            {
                message: {} as unknown as Message,
                event: {
                    uuid: '1',
                    event: 'test',
                    distinct_id: 'test',
                    timestamp: '2021-01-01',
                    token: 'token',
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
                } as unknown as PipelineEvent,
            },
        ]

        await deduplicateEvents(deduplicationRedis, messages)

        expect(deduplicationRedis.deduplicate).toHaveBeenCalledWith({
            keys: ['7a184cabe9cce485b181a9b8113845fededc36f56d7d4eff4fbebca53abd55f7'],
        })
    })

    it('should handle empty messages', async () => {
        const messages: IncomingEvent[] = []
        await deduplicateEvents(deduplicationRedis, messages)
        expect(deduplicationRedis.deduplicate).not.toHaveBeenCalled()
    })
})
