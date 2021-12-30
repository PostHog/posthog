import { Meta } from '@storybook/react'
import { keaStory } from 'lib/storybook/kea-story'

import eventsState from './events.json'
import { PerformanceWaterfall } from 'scenes/APM/PerformanceWaterfall'

export default {
    title: 'PostHog/Scenes/APM',
} as Meta

export const PerformanceWaterfallView = keaStory(PerformanceWaterfall, eventsState)
