import { useEffect } from 'react'
import { Meta } from '@storybook/react'
import { router } from 'kea-router'
import { urls } from 'scenes/urls'
import { App } from 'scenes/App'
import { mswDecorator, useFeatureFlags } from '~/mocks/browser'
import { FeatureType } from '~/types'
import { EMPTY_PAGINATED_RESPONSE } from '~/mocks/handlers'
import { FEATURE_FLAGS } from 'lib/constants'

export default {
    title: 'Scenes-App/Features',
    parameters: {
        layout: 'fullscreen',
        options: { showPanel: false },
        testOptions: {
            excludeNavigationFromSnapshot: true,
        },
        viewMode: 'story',
        mockDate: '2023-01-28', // To stabilize relative dates
    },
    decorators: [
        mswDecorator({
            get: {
                '/api/projects/:team_id/features': EMPTY_PAGINATED_RESPONSE,
                '/api/projects/:team_id/features/:flagId/': {} as FeatureType,
            },
        }),
    ],
} as Meta

export function FeaturesList(): JSX.Element {
    useFeatureFlags([FEATURE_FLAGS.FEATURE_MANAGEMENT])
    useEffect(() => {
        router.actions.push(urls.features())
    }, [])
    return <App />
}

export function NewFeatureFlag(): JSX.Element {
    useFeatureFlags([FEATURE_FLAGS.FEATURE_MANAGEMENT])
    useEffect(() => {
        router.actions.push(urls.feature('new'))
    }, [])
    return <App />
}
