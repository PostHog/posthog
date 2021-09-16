import { Meta } from '@storybook/react'
import { keaStory } from 'lib/storybook/kea-story'

import { ManageEvents } from '../Events'

import eventsState from './events.json'

export default {
    title: 'PostHog/Scenes/Events',
} as Meta

export const AllEvents = keaStory(ManageEvents, eventsState)
