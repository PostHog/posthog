import { useEffect } from 'react'
import { Meta } from '@storybook/react'
import { router } from 'kea-router'
import { urls } from 'scenes/urls'
import { App } from 'scenes/App'
import { mswDecorator } from '~/mocks/browser'
import featureFlags from './__mocks__/feature_flags.json'
import { useAvailableFeatures } from '~/mocks/features'
import { AvailableFeature } from '~/types'

const meta: Meta = {
    title: 'Scenes-App/Feature Flags',
    parameters: {
        layout: 'fullscreen',
        testOptions: {
            excludeNavigationFromSnapshot: true,
        },
        viewMode: 'story',
        mockDate: '2023-01-28', // To stabilize relative dates
    },
    decorators: [
        mswDecorator({
            get: {
                '/api/projects/:team_id/feature_flags': featureFlags,
                '/api/projects/:team_id/feature_flags/1111111111111/': [
                    404,
                    {
                        type: 'invalid',
                        code: 'not_found',
                        detail: 'Not found.',
                    },
                ],
                '/api/projects/:team_id/feature_flags/:flagId/': (req) => [
                    200,
                    featureFlags.results.find((r) => r.id === Number(req.params['flagId'])),
                ],
            },
        }),
    ],
}
export default meta
export function FeatureFlagsList(): JSX.Element {
    useEffect(() => {
        router.actions.push(urls.featureFlags())
    }, [])
    return <App />
}

export function NewFeatureFlag(): JSX.Element {
    useEffect(() => {
        router.actions.push(urls.featureFlag('new'))
    }, [])
    return <App />
}

export function EditFeatureFlag(): JSX.Element {
    useEffect(() => {
        router.actions.push(urls.featureFlag(1779))
    }, [])
    return <App />
}

export function EditMultiVariateFeatureFlag(): JSX.Element {
    useEffect(() => {
        useAvailableFeatures([AvailableFeature.MULTIVARIATE_FLAGS])
        router.actions.push(urls.featureFlag(1502))
    }, [])
    return <App />
}

export function FeatureFlagNotFound(): JSX.Element {
    useEffect(() => {
        router.actions.push(urls.featureFlag(1111111111111))
    }, [])
    return <App />
}
