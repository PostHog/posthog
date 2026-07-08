import { PluginEvent } from '~/plugin-scaffold'

export const createEvent = (event: string, properties: Record<string, unknown>): PluginEvent => ({
    event,
    distinct_id: 'user-123',
    team_id: 1,
    properties,
    uuid: 'test-uuid',
    timestamp: new Date().toISOString(),
    ip: '127.0.0.1',
    site_url: 'https://app.posthog.com',
    now: new Date().toISOString(),
})
