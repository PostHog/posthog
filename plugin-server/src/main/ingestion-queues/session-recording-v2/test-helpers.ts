import { Message } from 'node-rdkafka'

export function createTestMessage(overrides: Partial<Message> = {}): Message {
    return {
        partition: 0,
        value: Buffer.alloc(1024),
        size: 1024,
        topic: 'test-topic',
        offset: 0,
        timestamp: Date.now(),
        ...overrides,
    }
}
