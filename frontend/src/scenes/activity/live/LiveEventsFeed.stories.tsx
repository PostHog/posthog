import { Meta, StoryFn } from '@storybook/react'

import { LiveEventsFeed, LiveEventsFeedProps } from './LiveEventsFeed'

const meta: Meta<typeof LiveEventsFeed> = {
    title: 'Scenes-App/Live events/LiveEventsFeed',
    component: LiveEventsFeed,
    parameters: {
        testOptions: { viewport: { width: 520, height: 420 } },
    },
}
export default meta

const Template: StoryFn<typeof LiveEventsFeed> = (props: LiveEventsFeedProps) => <LiveEventsFeed {...props} />

export const StreamPaused = Template.bind({})
StreamPaused.args = { events: [], streamPaused: true }

export const StreamFailed = Template.bind({})
StreamFailed.args = {
    events: [],
    streamError: {
        message: 'The live event stream failed with error 504. Try again, and contact us if it keeps happening.',
        retrying: false,
    },
    onRetry: () => {},
}

export const StreamReconnecting = Template.bind({})
StreamReconnecting.args = {
    events: [],
    streamError: { message: 'Lost the connection to the live event stream. Trying to reconnect.', retrying: true },
    onRetry: () => {},
}

export const StreamFailedWithEvents = Template.bind({})
StreamFailedWithEvents.args = {
    events: [
        {
            uuid: '0194f000-0000-7000-8000-000000000001',
            event: '$pageview',
            properties: { $current_url: 'https://example.com/pricing' },
            timestamp: '2026-01-01T00:00:00.000Z',
            team_id: 1,
            distinct_id: 'visitor-1',
            created_at: '2026-01-01T00:00:00.000Z',
        },
    ],
    // The timestamp column re-renders every second against the wall clock, so it stays out of the
    // story to keep the visual snapshot stable.
    columns: ['event', 'url'],
    streamError: {
        message: 'The live event stream failed with error 504. Try again, and contact us if it keeps happening.',
        retrying: false,
    },
    onRetry: () => {},
}
