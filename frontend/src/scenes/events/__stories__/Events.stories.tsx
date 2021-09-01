import React from 'react'
import { ComponentMeta } from '@storybook/react'
import { KeaStory } from 'lib/storybook/kea-story'

import { ManageEvents } from '../Events'

import eventsState from './events.json'

export default {
    title: 'PostHog/Scenes/Events',
    component: ManageEvents,
} as ComponentMeta<typeof ManageEvents>

export const AllEvents = (): JSX.Element => (
    <KeaStory state={eventsState}>
        <ManageEvents />
    </KeaStory>
)
