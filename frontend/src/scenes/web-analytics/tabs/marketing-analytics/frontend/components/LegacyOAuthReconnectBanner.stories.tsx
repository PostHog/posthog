import type { Meta, StoryObj } from '@storybook/react'
import { useMountedLogic } from 'kea'

import { FEATURE_FLAGS } from 'lib/constants'
import { integrationsLogic } from 'lib/integrations/integrationsLogic'

import { useStorybookMocks } from '~/mocks/browser'

import { LegacyOAuthReconnectBanner } from './LegacyOAuthReconnectBanner'

const meta: Meta<typeof LegacyOAuthReconnectBanner> = {
    title: 'Scenes-App/Marketing Analytics/Legacy OAuth reconnect warning',
    component: LegacyOAuthReconnectBanner,
    parameters: { featureFlags: [FEATURE_FLAGS.LEGACY_OAUTH_RECONNECT_WARNING] },
    render: () => {
        useStorybookMocks({
            get: {
                '/api/projects/:team_id/integrations': {
                    results: [{ id: 1, kind: 'bing-ads', config: { oauth_uses_legacy_client: true } }],
                },
            },
        })
        useMountedLogic(integrationsLogic)
        return <LegacyOAuthReconnectBanner />
    },
}
export default meta

type Story = StoryObj<typeof LegacyOAuthReconnectBanner>
export const Warning: Story = {}
