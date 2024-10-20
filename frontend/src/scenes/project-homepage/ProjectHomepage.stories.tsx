import { Meta } from '@storybook/react'
import { router } from 'kea-router'
import { useEffect } from 'react'
import { App } from 'scenes/App'
import { urls } from 'scenes/urls'

import { mswDecorator } from '~/mocks/browser'
import { EMPTY_PAGINATED_RESPONSE } from '~/mocks/handlers'

const meta: Meta = {
    title: 'Scenes-App/Project Homepage',
    decorators: [
        mswDecorator({
            get: {
                '/api/environments/:team_id/dashboards/': require('../dashboard/__mocks__/dashboards.json'),
                '/api/environments/:team_id/dashboards/1/': require('../dashboard/__mocks__/dashboard1.json'),
                '/api/environments/:team_id/dashboards/1/collaborators/': [],
                '/api/environments/:team_id/session_recordings/': EMPTY_PAGINATED_RESPONSE,
                '/api/environments/:team_id/insights/my_last_viewed/': [],
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
export const ProjectHomepage = (): JSX.Element => {
    useEffect(() => {
        router.actions.push(urls.projectHomepage())
    }, [])
    return <App />
}
