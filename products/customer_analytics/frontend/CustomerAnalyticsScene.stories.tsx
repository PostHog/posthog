import { Meta } from '@storybook/react'

import { FEATURE_FLAGS } from 'lib/constants'
import { useDelayedOnMountEffect } from 'lib/hooks/useOnMountEffect'
import { App } from 'scenes/App'
import { urls } from 'scenes/urls'

import { mswDecorator, useStorybookMocks } from '~/mocks/browser'
import { useAvailableFeatures } from '~/mocks/features'
import { AvailableFeature } from '~/types'

import actorsQueryMock from './__mocks__/ActorsQuery.json'
import funnelsQueryMock from './__mocks__/FunnelsQuery.json'
import lifecycleQueryMock from './__mocks__/LifecycleQuery.json'
import trendsQueryMock from './__mocks__/TrendsQuery.json'
import { BusinessType, customerAnalyticsSceneLogic } from './customerAnalyticsSceneLogic'

const MOCK_GROUP_TYPES = [
    { group_type: 'organization', group_type_index: 0, name_singular: 'Organization', name_plural: 'Organizations' },
]

function setBusinessTypeOnMountedLogic(businessType: BusinessType): void {
    for (const logic of customerAnalyticsSceneLogic.findAllMounted()) {
        logic.actions.setBusinessType(businessType)
    }
}

const meta: Meta = {
    component: App,
    title: 'Scenes-App/Customer Analytics',
    parameters: {
        layout: 'fullscreen',
        viewMode: 'story',
        mockDate: '2026-02-05',
        pageUrl: urls.customerAnalytics(),
        featureFlags: [FEATURE_FLAGS.CUSTOMER_ANALYTICS],
        testOptions: {
            waitForLoadersToDisappear: true,
        },
    },
    decorators: [
        mswDecorator({
            post: {
                '/api/environments/:team_id/query': (req) => {
                    const query = (req.body as any).query
                    const queryKind = query.kind

                    if (queryKind === 'DatabaseSchemaQuery') {
                        return [200, { tables: {}, joins: [] }]
                    } else if (queryKind === 'TrendsQuery') {
                        return [200, trendsQueryMock]
                    } else if (queryKind === 'FunnelsQuery') {
                        return [200, funnelsQueryMock]
                    } else if (queryKind === 'LifecycleQuery') {
                        return [200, lifecycleQueryMock]
                    } else if (queryKind === 'ActorsQuery') {
                        return [200, actorsQueryMock]
                    }

                    return [200, { results: [] }]
                },
            },
        }),
    ],
}
export default meta

export function B2CDashboard(): JSX.Element {
    useDelayedOnMountEffect(() => {
        setBusinessTypeOnMountedLogic('b2c')
    })

    return <App />
}

export function B2BDashboard(): JSX.Element {
    useAvailableFeatures([AvailableFeature.GROUP_ANALYTICS])

    useStorybookMocks({
        get: {
            '/api/projects/:team_id/groups_types/': MOCK_GROUP_TYPES,
            '/api/environments/:team_id/groups_types/': MOCK_GROUP_TYPES,
        },
    })

    useDelayedOnMountEffect(() => {
        setBusinessTypeOnMountedLogic('b2b')
    })

    return <App />
}

export function B2BPayGate(): JSX.Element {
    useDelayedOnMountEffect(() => {
        setBusinessTypeOnMountedLogic('b2b')
    })

    return <App />
}
