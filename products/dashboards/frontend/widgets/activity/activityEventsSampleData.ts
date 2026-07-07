import type { ActivityEventsWidgetEvent } from './ActivityEventsWidgetRow'

export const activityEventsSampleEvents: ActivityEventsWidgetEvent[] = [
    {
        uuid: 'overview-event-1',
        event: '$pageview',
        person: { display_name: 'Alex Chen', id: '1', distinct_id: 'user-1' },
        url: 'https://app.example.test/dashboard',
        lib: 'web',
        timestamp: '2026-05-26T08:04:08.000Z',
    },
    {
        uuid: 'overview-event-2',
        event: 'file uploaded',
        person: { display_name: 'Sam Rivera', id: '2', distinct_id: 'user-2' },
        url: 'https://app.example.test/files',
        lib: 'posthog-python',
        timestamp: '2026-05-26T07:58:21.000Z',
    },
    {
        uuid: 'overview-event-3',
        event: '$autocapture',
        person: { display_name: 'Jordan Lee', id: '3', distinct_id: 'user-3' },
        url: 'https://app.example.test/settings',
        lib: 'web',
        timestamp: '2026-05-26T07:41:05.000Z',
    },
]
