import { MOCK_DEFAULT_ORGANIZATION, MOCK_DEFAULT_USER } from 'lib/api.mock'

import type { Meta, StoryObj } from '@storybook/react'

import { mswDecorator } from '~/mocks/browser'

import { ReplayDataRetentionSettings } from './SessionRecordingSettings'

function orgWithRetention(limit: number | null): Record<string, any> {
    return {
        ...MOCK_DEFAULT_ORGANIZATION,
        available_product_features: limit
            ? [{ key: 'session_replay_data_retention', name: 'Data retention', limit, unit: 'months' }]
            : [],
    }
}

function mocks(limit: number | null): any {
    return mswDecorator({
        get: {
            '/api/users/@me/': () => [200, { ...MOCK_DEFAULT_USER, organization: orgWithRetention(limit) }],
            '/api/organizations/@current/': () => [200, orgWithRetention(limit)],
        },
    })
}

const meta: Meta<typeof ReplayDataRetentionSettings> = {
    title: 'Scenes-App/Settings/Replay data retention',
    component: ReplayDataRetentionSettings,
    parameters: { layout: 'padded', testOptions: { include: false } },
}
export default meta

type Story = StoryObj<typeof ReplayDataRetentionSettings>

export const BoostPackageStillOn30Days: Story = { decorators: [mocks(12)] }
export const NoEntitlement: Story = { decorators: [mocks(null)] }
