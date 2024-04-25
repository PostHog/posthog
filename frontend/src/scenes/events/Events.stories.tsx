import { Meta } from '@storybook/react'
import { router } from 'kea-router'
import { useEffect } from 'react'
import { App } from 'scenes/App'
import { urls } from 'scenes/urls'

import { mswDecorator } from '~/mocks/browser'

import eventsQuery from './__mocks__/eventsQuery.json'

const meta: Meta = {
    title: 'Scenes-App/Events',
    decorators: [
        mswDecorator({
            post: {
                '/api/projects/:team_id/query': eventsQuery,
            },
        }),
    ],
    parameters: {
        layout: 'fullscreen',
        viewMode: 'story',
        mockDate: '2023-01-28', // To stabilize relative dates
    },
}
export default meta
export const EventExplorer = (): JSX.Element => {
    useEffect(() => {
        router.actions.push(urls.events())
    }, [])

    return <App />
}
