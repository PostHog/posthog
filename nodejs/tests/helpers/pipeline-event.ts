import { PipelineEvent } from '../../src/types'

export function createTestPipelineEvent(overrides: Partial<PipelineEvent> = {}): PipelineEvent {
    return {
        distinct_id: 'test-distinct-id',
        ip: '127.0.0.1',
        site_url: 'https://example.com',
        now: '2021-01-01T00:00:00Z',
        event: '$pageview',
        uuid: '123e4567-e89b-12d3-a456-426614174000',
        properties: {},
        ...overrides,
    }
}
