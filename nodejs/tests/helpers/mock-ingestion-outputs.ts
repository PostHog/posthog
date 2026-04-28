import { IngestionOutputs } from '../../src/ingestion/outputs/ingestion-outputs'

export function createMockIngestionOutputs<O extends string>(): jest.Mocked<IngestionOutputs<O>> {
    return {
        produce: jest.fn().mockResolvedValue(undefined),
        queueMessages: jest.fn().mockResolvedValue(undefined),
        checkHealth: jest.fn().mockResolvedValue([]),
        checkTopics: jest.fn().mockResolvedValue([]),
    } as unknown as jest.Mocked<IngestionOutputs<O>>
}
