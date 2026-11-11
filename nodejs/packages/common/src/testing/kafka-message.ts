import { Message } from 'node-rdkafka'

/**
 * Helper function to create a Kafka Message for tests with sensible defaults.
 *
 * @param overrides - Partial Message to override defaults
 * @returns Complete Message object
 */
export function createTestMessage(overrides: Partial<Message> = {}): Message {
    return {
        value: Buffer.from('test-value'),
        key: Buffer.from('test-key'),
        offset: 100,
        partition: 5,
        topic: 'test-topic',
        size: 10,
        ...overrides,
    }
}
