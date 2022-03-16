import { Meta } from '@storybook/react'
import { keaStory } from 'storybook/kea-story'

import eventsState from './events.json'
import { EventsTable } from 'scenes/events'

export default {
    title: 'Scenes/Events',
} as Meta

export const AllEvents = keaStory(EventsTable, eventsState)
