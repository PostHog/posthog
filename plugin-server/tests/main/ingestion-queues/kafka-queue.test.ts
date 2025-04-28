import { Assignment } from 'node-rdkafka'

import { countPartitionsPerTopic } from '../../../src/kafka/consumer'

jest.mock('../../../src/utils/logger')
jest.setTimeout(70000) // 60 sec timeout

describe('countPartitionsPerTopic', () => {
    it('should correctly count the number of partitions per topic', () => {
        const assignments: Assignment[] = [
            { topic: 'topic1', partition: 0 },
            { topic: 'topic1', partition: 1 },
            { topic: 'topic2', partition: 0 },
            { topic: 'topic2', partition: 1 },
            { topic: 'topic2', partition: 2 },
            { topic: 'topic3', partition: 0 },
        ]

        const result = countPartitionsPerTopic(assignments)
        expect(result.get('topic1')).toBe(2)
        expect(result.get('topic2')).toBe(3)
        expect(result.get('topic3')).toBe(1)
        expect(result.size).toBe(3)
    })
})
