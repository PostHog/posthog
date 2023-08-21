import { Meta } from '@storybook/react'
import { mswDecorator } from '~/mocks/browser'
import { useEffect } from 'react'
import { router } from 'kea-router'
import { urls } from 'scenes/urls'
import { App } from 'scenes/App'
import { EMPTY_PAGINATED_RESPONSE } from '~/mocks/handlers'
import { useActions } from 'kea'
import { themeLogic } from './themeLogic'
import { with3000 } from 'storybook/decorators/with3000'

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
        with3000,
    ],
    parameters: {
        layout: 'fullscreen',
        viewMode: 'story',
        mockDate: '2023-02-01',
    },
}
export default meta
export function LightMode(): JSX.Element {
    const { overrideTheme } = useActions(themeLogic)
    useEffect(() => {
        router.actions.push(urls.projectHomepage())
        overrideTheme(false)
    }, [])

    return <App />
}

export function DarkMode(): JSX.Element {
    const { overrideTheme } = useActions(themeLogic)
    useEffect(() => {
        router.actions.push(urls.projectHomepage())
        overrideTheme(true)
    }, [])

    return <App />
}
