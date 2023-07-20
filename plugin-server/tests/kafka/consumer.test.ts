import { Message } from 'node-rdkafka-acosom'

import { commitOffsetsForMessages, findOffsetsToCommit } from '../../src/kafka/consumer'

describe('consumer', () => {
    const messages = [
        { topic: 'topic1', partition: 1, offset: 10 },
        { topic: 'topic1', partition: 1, offset: 11 },
        { topic: 'topic1', partition: 1, offset: 12 },
        { topic: 'topic1', partition: 2, offset: 22 },
        { topic: 'topic1', partition: 2, offset: 21 },
        { topic: 'topic1', partition: 2, offset: 20 },
        { topic: 'topic2', partition: 1, offset: 30 },
    ]

    describe('findOffsetsToCommit', () => {
        it('should return the highest offset for each topic partition', () => {
            expect(findOffsetsToCommit(messages)).toEqual([
                { topic: 'topic1', partition: 1, offset: 12 },
                { topic: 'topic1', partition: 2, offset: 22 },
                { topic: 'topic2', partition: 1, offset: 30 },
            ])
        })

        it('should return an empty list if given', () => {
            expect(findOffsetsToCommit([])).toEqual([])
        })
    })

    describe('commitOffsetsForMessages', () => {
        it('should commit the highest offset for each topic partition plus 1', () => {
            const mockCommit = jest.fn()

            commitOffsetsForMessages(messages as Message[], { commit: mockCommit } as any)

            expect(mockCommit).toHaveBeenCalledTimes(1)
            expect(mockCommit).toHaveBeenCalledWith([
                { offset: 13, partition: 1, topic: 'topic1' },
                { offset: 23, partition: 2, topic: 'topic1' },
                { offset: 31, partition: 1, topic: 'topic2' },
            ])
        })
    })
})
