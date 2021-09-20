import React from 'react'
import { Meta } from '@storybook/react'
import { keaStory } from 'lib/storybook/kea-story'

import { ManageEvents } from '../Events'

import eventsState from './events.json'

export default {
    title: 'PostHog/Scenes/Events',
} as Meta

export const AllEvents = keaStory(ManageEvents, eventsState)

export const DesignProposal = (): JSX.Element => (
    <img
        src="https://user-images.githubusercontent.com/254612/130522734-4503a8b7-dead-4e66-a78e-b1cd773239a1.png"
        style={{ width: '100%' }}
    />
)
