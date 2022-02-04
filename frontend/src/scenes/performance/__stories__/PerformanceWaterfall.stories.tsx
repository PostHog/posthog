import { Meta } from '@storybook/react'
import { keaStory } from 'lib/storybook/kea-story'

import eventsState from './events.json'
import { WebPerformance } from 'scenes/performance/WebPerformance'

export default {
    title: 'PostHog/Scenes/WebPerformance',
} as Meta

export const WebPerformanceStory = keaStory(WebPerformance, eventsState)
