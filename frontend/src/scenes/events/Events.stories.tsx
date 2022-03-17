import { Meta } from '@storybook/react'

import { EventsTable } from 'scenes/events/index'
import React from 'react'
import { mswDecorator } from '~/mocks/browser'
import eventList from './__mocks__/eventList.json'

export default {
    title: 'Scenes/Events',
    decorators: [
        mswDecorator({
            get: { '/api/projects/1/events': { next: null, results: eventList } },
        }),
    ],
    parameters: { options: { showPanel: false }, viewMode: 'canvas' },
} as Meta

export const AllEvents = (): JSX.Element => {
    return <EventsTable pageKey="EventsTable" sceneUrl="/" />
}
