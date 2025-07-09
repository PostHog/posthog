import { Meta, StoryObj } from '@storybook/react'
import { App } from 'scenes/App'
import { urls } from 'scenes/urls'

import { mswDecorator } from '~/mocks/browser'

import featureFlags from './__mocks__/feature_flags.json'

const meta: Meta = {
    component: App,
    tags: ['ff'],
    title: 'Scenes-App/Feature Flags',
    parameters: {
        layout: 'fullscreen',
        viewMode: 'story',
        mockDate: '2023-01-28', // To stabilize relative dates
        pageUrl: urls.featureFlags(),
    },
    decorators: [
        mswDecorator({
            get: {
                '/api/projects/:team_id/integrations': {},

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
                '/api/projects/:team_id/feature_flags/:flagId/status': () => [
                    200,
                    {
                        status: 'active',
                        reason: 'Feature flag is active',
                    },
                ],
            },
            post: {
                '/api/environments/:team_id/query': {},
                // flag targeting has loaders, make sure they don't keep loading
                '/api/projects/:team_id/feature_flags/user_blast_radius/': () => [
                    200,
                    { users_affected: 120, total_users: 2000 },
                ],
            },
        }),
    ],
}
export default meta

type Story = StoryObj<typeof meta>
export const FeatureFlagsList: Story = {}

export const NewFeatureFlag: Story = {
    parameters: {
        pageUrl: urls.featureFlag('new'),
    },
}

export const EditFeatureFlag: Story = {
    parameters: {
        pageUrl: urls.featureFlag(1779),
    },
}

export const EditMultiVariateFeatureFlag: Story = {
    parameters: {
        pageUrl: urls.featureFlag(1502),
    },
}

export const EditRemoteConfigFeatureFlag: Story = {
    parameters: {
        pageUrl: urls.featureFlag(1738),
    },
}

export const EditEncryptedRemoteConfigFeatureFlag: Story = {
    parameters: {
        pageUrl: urls.featureFlag(1739),
    },
}

export const FeatureFlagNotFound: Story = {
    parameters: {
        pageUrl: urls.featureFlag(1111111111111),
    },
}
