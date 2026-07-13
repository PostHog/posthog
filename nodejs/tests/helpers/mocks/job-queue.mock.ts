import { JobQueue } from '../../../src/cdp/services/job-queue/job-queue.interface'

export function createMockJobQueue(): jest.Mocked<JobQueue> {
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
    } as jest.Mocked<JobQueue>
}
