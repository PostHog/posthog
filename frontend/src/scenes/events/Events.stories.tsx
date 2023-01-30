import { Meta } from '@storybook/react'

import { useEffect } from 'react'
import { mswDecorator } from '~/mocks/browser'
import eventList from './__mocks__/eventList.json'
import { router } from 'kea-router'
import { urls } from 'scenes/urls'
import { App } from 'scenes/App'
import { useActions } from 'kea'
import { eventsTableLogic, EventsTableLogicProps } from './eventsTableLogic'

export default {
    title: 'Scenes-App/Events',
    decorators: [
        mswDecorator({
            get: { '/api/projects/:team_id/events': { next: null, results: eventList } },
        }),
    ],
    parameters: {
        layout: 'fullscreen',
        options: { showPanel: false },
        viewMode: 'story',

        mockDate: '2023-01-28', // To stabilize relative dates
    },
} as Meta

export const LiveEvents = (): JSX.Element => {
    const { setPollingActive } = useActions(
        eventsTableLogic({ key: 'EventsTable', sceneUrl: urls.events() } as EventsTableLogicProps)
    )
    useEffect(() => {
        router.actions.push(urls.events())
        setPollingActive(false) // Disable polling so that the story is static
    }, [])

    return <App />
}
