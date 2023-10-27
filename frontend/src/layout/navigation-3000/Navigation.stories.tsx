import { Meta } from '@storybook/react'
import { mswDecorator, setFeatureFlags } from '~/mocks/browser'
import { useEffect } from 'react'
import { router } from 'kea-router'
import { urls } from 'scenes/urls'
import { App } from 'scenes/App'
import { EMPTY_PAGINATED_RESPONSE } from '~/mocks/handlers'

const meta: Meta = {
    title: 'PostHog 3000/Navigation',
    decorators: [
        mswDecorator({
            get: {
                '/api/projects/:team_id/dashboards/': require('../../scenes/dashboard/__mocks__/dashboards.json'),
                '/api/projects/:team_id/dashboards/1/': require('../../scenes/dashboard/__mocks__/dashboard1.json'),
                '/api/projects/:team_id/dashboards/1/collaborators/': [],
                '/api/projects/:team_id/insights/my_last_viewed/': require('../../scenes/saved-insights/__mocks__/insightsMyLastViewed.json'),
                '/api/projects/:team_id/session_recordings/': EMPTY_PAGINATED_RESPONSE,
            },
        }),
    ],
    parameters: {
        layout: 'fullscreen',
        viewMode: 'story',
        mockDate: '2023-02-01',
    },
}
export default meta

export function NavigationBase(): JSX.Element {
    setFeatureFlags(['posthog-3000'])
    useEffect(() => {
        router.actions.push(urls.projectHomepage())
    }, [])

    return <App />
}

export function Navigation3000(): JSX.Element {
    setFeatureFlags(['posthog-3000', 'posthog-3000-nav'])
    useEffect(() => {
        router.actions.push(urls.projectHomepage())
    }, [])

    return <App />
}
