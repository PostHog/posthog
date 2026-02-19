import { PluginEvent } from '@posthog/plugin-scaffold'

export function createTestPluginEvent(overrides: Partial<PluginEvent> = {}): PluginEvent {
    return {
        distinct_id: 'test-distinct-id',
        ip: null,
        site_url: 'http://localhost',
        team_id: 1,
        now: '2020-02-23T02:15:00Z',
        event: '$pageview',
        uuid: '123e4567-e89b-12d3-a456-426614174000',
        properties: {},
        ...overrides,
    }
}
