import { Meta } from '@storybook/react'
import eventsResponse from './__mocks__/eventsResponse.json'
import { useEffect } from 'react'
import { mswDecorator } from '~/mocks/browser'
import { router } from 'kea-router'
import { App } from 'scenes/App'
import { urls } from 'scenes/urls'

export default {
    title: 'Scenes-App/Web Performance',
    parameters: {
        layout: 'fullscreen',
        options: { showPanel: false },
        viewMode: 'story',
        testOptions: {
            excludeNavigationFromSnapshot: true,
        },
    },
    decorators: [
        mswDecorator({
            get: {
                '/api/projects/:team_id/events': {
                    results: eventsResponse,
                },
            },
        }),
    ],
} as Meta

export const WebPerformance_ = (): JSX.Element => {
    useEffect(() => {
        router.actions.push(urls.webPerformance())
    })
    return <App />
}
