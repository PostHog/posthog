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

export const WaitingForEvents = Template.bind({})
WaitingForEvents.args = { events: [] }

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
