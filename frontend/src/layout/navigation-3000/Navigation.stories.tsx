import { Meta } from '@storybook/react'
import { mswDecorator, useFeatureFlags } from '~/mocks/browser'
import { useEffect } from 'react'
import { router } from 'kea-router'
import { urls } from 'scenes/urls'
import { FEATURE_FLAGS } from 'lib/constants'
import { App } from 'scenes/App'
import { EMPTY_PAGINATED_RESPONSE } from '~/mocks/handlers'
import { useActions } from 'kea'
import { themeLogic } from './themeLogic'

export default {
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
        options: { showPanel: false },
        viewMode: 'story',
        mockDate: '2023-02-01',
    },
} as Meta

export function LightMode(): JSX.Element {
    const { syncDarkModePreference } = useActions(themeLogic)
    useFeatureFlags([FEATURE_FLAGS.POSTHOG_3000])
    useEffect(() => {
        router.actions.push(urls.projectHomepage())
        syncDarkModePreference(false)
    }, [])

    return <App />
}

export function DarkMode(): JSX.Element {
    const { syncDarkModePreference } = useActions(themeLogic)
    useFeatureFlags([FEATURE_FLAGS.POSTHOG_3000])
    useEffect(() => {
        router.actions.push(urls.projectHomepage())
        syncDarkModePreference(true)
    }, [])

    return <App />
}
