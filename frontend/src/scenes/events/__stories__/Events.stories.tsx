import { Meta } from '@storybook/react'
import { keaStory } from 'lib/storybook/kea-story'

import eventsState from './events.json'
import { EventsTable } from 'scenes/events'

export default {
    title: 'PostHog/Scenes/Events',
} as Meta

export const AllEvents = keaStory(EventsTable, eventsState)
