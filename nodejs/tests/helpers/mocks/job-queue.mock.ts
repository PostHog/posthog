import { IdempotentJobQueue } from '../../../src/cdp/services/job-queue/job-queue.interface'

export function createMockJobQueue(): jest.Mocked<IdempotentJobQueue> {
    return {
        queueInvocations: jest.fn().mockResolvedValue(undefined),
        queueInvocationResults: jest.fn().mockResolvedValue(undefined),
        startAsProducer: jest.fn().mockResolvedValue(undefined),
        startAsConsumer: jest.fn().mockResolvedValue(undefined),
        stopConsumer: jest.fn().mockResolvedValue(undefined),
        stopProducer: jest.fn().mockResolvedValue(undefined),
        isHealthy: jest.fn(),
        dequeueInvocations: jest.fn().mockResolvedValue(undefined),
        cancelInvocations: jest.fn().mockResolvedValue(undefined),
        heartbeatInvocations: jest.fn().mockResolvedValue(undefined),
        queueInvocationsIdempotently: jest.fn().mockResolvedValue([]),
        getIdempotencyKeyFingerprint: jest.fn().mockResolvedValue(null),
    } as jest.Mocked<IdempotentJobQueue>
}
