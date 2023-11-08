import { Meta } from '@storybook/react'

import { useEffect } from 'react'
import { mswDecorator } from '~/mocks/browser'
import eventsQuery from './__mocks__/eventsQuery.json'
import { router } from 'kea-router'
import { urls } from 'scenes/urls'
import { App } from 'scenes/App'

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
        testOptions: {
            excludeNavigationFromSnapshot: true,
        },
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
