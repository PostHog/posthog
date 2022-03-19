import { Meta } from '@storybook/react'

import React, { useEffect } from 'react'
import { mswDecorator } from '~/mocks/browser'
import eventList from './__mocks__/eventList.json'
import { router } from 'kea-router'
import { urls } from 'scenes/urls'
import { App } from 'scenes/App'

export default {
    title: 'Scenes-App/Events',
    decorators: [
        mswDecorator({
            get: { '/api/projects/:projectId/events': { next: null, results: eventList } },
        }),
    ],
    parameters: { layout: 'fullscreen', options: { showPanel: false }, viewMode: 'canvas' },
} as Meta

export const LiveEvents = (): JSX.Element => {
    useEffect(() => {
        router.actions.push(urls.events())
    }, [])
    return <App />
}
