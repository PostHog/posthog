import { MOCK_TEAM_ID } from 'lib/api.mock'

import { Decorator, Meta, StoryObj } from '@storybook/react'

import { App } from 'scenes/App'
import { urls } from 'scenes/urls'

import type { DeviceGrantDetailsApi } from '~/generated/core/api.schemas'
import { mswDecorator } from '~/mocks/browser'

const GRANT: DeviceGrantDetailsApi = {
    user_code: 'BCDF-GHJK',
    client_id: 'https://posthog.com/.well-known/oauth/hog/client-metadata.json',
    client_name: 'hog',
    logo_uri: null,
    is_verified: true,
    scopes: ['openid', 'email', 'insight:write', 'dashboard:write', 'query:read', 'feature_flag:read'],
    required_scopes: ['openid', 'feature_flag:read'],
    granted_scopes: [],
    expires_at: '2023-02-01T10:30:00Z',
}

// Answers the code lookup with this grant, and lists two projects so the picker can preselect the current one.
const withGrant = (grant: Partial<DeviceGrantDetailsApi>): Decorator =>
    mswDecorator({
        get: {
            '/api/organizations/:organization_id/projects/': {
                results: [
                    { id: MOCK_TEAM_ID, name: 'Default project' },
                    { id: MOCK_TEAM_ID + 1, name: 'Staging' },
                ],
                next: null,
            },
        },
        post: {
            '/api/oauth_device/lookup/': { ...GRANT, ...grant },
        },
    })

const meta: Meta = {
    title: 'Scenes-App/OAuth/Device login',
    parameters: {
        layout: 'fullscreen',
        viewMode: 'story',
        mockDate: '2023-02-01',
        pageUrl: `${urls.oauthDeviceAuthorize()}?code=${GRANT.user_code}`,
        testOptions: {
            waitForSelector: '[data-attr="oauth-device-user-code"]',
        },
    },
}

export default meta

type Story = StoryObj<{}>

export const FewPermissions: Story = {
    decorators: [withGrant({})],
    render: () => <App />,
}

export const ManyPermissions: Story = {
    render: () => <App />,
    decorators: [
        withGrant({
            scopes: [
                'openid',
                'email',
                'profile',
                'organization:read',
                'project:write',
                'feature_flag:write',
                'experiment:write',
                'insight:write',
                'dashboard:write',
                'query:read',
                'survey:write',
                'error_tracking:read',
                'logs:read',
            ],
            required_scopes: ['openid'],
        }),
    ],
}

// The server marks the scopes a step-up adds as required, so every row left in the list is locked.
export const StepUp: Story = {
    render: () => <App />,
    decorators: [
        withGrant({
            scopes: ['openid', 'email', 'insight:read', 'dashboard:write', 'feature_flag:write'],
            required_scopes: ['openid', 'dashboard:write', 'feature_flag:write'],
            granted_scopes: [
                {
                    project_id: null,
                    organization_id: null,
                    scopes: ['openid', 'email', 'insight:read', 'dashboard:read'],
                },
            ],
        }),
    ],
}
