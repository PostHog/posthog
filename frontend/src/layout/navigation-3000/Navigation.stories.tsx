import { Meta } from '@storybook/react'
import { useActions } from 'kea'
import { router } from 'kea-router'
import { FEATURE_FLAGS } from 'lib/constants'
import { useEffect } from 'react'
import { App } from 'scenes/App'
import { urls } from 'scenes/urls'

import { mswDecorator, setFeatureFlags } from '~/mocks/browser'
import { EMPTY_PAGINATED_RESPONSE } from '~/mocks/handlers'

import { navigationLogic } from '../navigation/navigationLogic'

const meta: Meta = {
    title: 'PostHog 3000/Navigation',
    decorators: [
        mswDecorator({
            get: {
                '/api/environments/:team_id/dashboards/': require('../../scenes/dashboard/__mocks__/dashboards.json'),
                '/api/environments/:team_id/dashboards/1/': require('../../scenes/dashboard/__mocks__/dashboard1.json'),
                '/api/environments/:team_id/dashboards/1/collaborators/': [],
                '/api/environments/:team_id/insights/my_last_viewed/': require('../../scenes/saved-insights/__mocks__/insightsMyLastViewed.json'),
                '/api/environments/:team_id/session_recordings/': EMPTY_PAGINATED_RESPONSE,
                '/api/environments/:team_id/insight_variables/': EMPTY_PAGINATED_RESPONSE,
            },
        }),
    ],
    parameters: {
        layout: 'fullscreen',
        testOptions: {
            includeNavigationInSnapshot: true,
            waitForLoadersToDisappear: true,
            snapshotBrowsers: ['chromium'],
        },
        viewMode: 'story',
        mockDate: '2023-02-01',
    },
}
export default meta

export function NavigationBase(): JSX.Element {
    useEffect(() => {
        router.actions.push(urls.projectHomepage())
    }, [])

    return <App />
}

export function Navigation3000(): JSX.Element {
    const { openAccountPopover } = useActions(navigationLogic)
    setFeatureFlags([FEATURE_FLAGS.POSTHOG_3000_NAV])
    useEffect(() => {
        router.actions.push(urls.projectHomepage())
        openAccountPopover()
    }, [openAccountPopover])

    return <App />
}
