import { Meta, StoryObj } from '@storybook/react'

import { urls } from 'scenes/urls'

import { useStorybookMocks } from '~/mocks/browser'
import preflightJson from '~/mocks/fixtures/_preflight.json'

import { CredentialReview } from './CredentialReview'

const meta: Meta<typeof CredentialReview> = {
    title: 'Scenes-Other/Credential Review',
    component: CredentialReview,
    parameters: {
        layout: 'fullscreen',
        viewMode: 'story',
        pageUrl: urls.credentialReview(),
        testOptions: { waitForLoadersToDisappear: true },
    },
}
export default meta

type Story = StoryObj<typeof CredentialReview>

const cloudPreflight = {
    ...preflightJson,
    cloud: true,
    realm: 'cloud',
}

const partnerApiKey = {
    id: 'key-1',
    label: 'Partner setup key',
    description: null,
    created_at: '2026-08-01T09:12:00Z',
    last_used_at: null,
    last_rolled_at: null,
    user_id: 1,
    is_legacy_hashing: false,
    scopes: ['insight:read', 'event:read', 'feature_flag:write'],
    scoped_organizations: [],
    scoped_teams: [2],
    mask_value: 'phx_...abcd',
}

const partnerApp = {
    id: '0192f0e4-1f2a-7000-8000-000000000001',
    name: 'Acme Deploy',
    logo_uri: null,
    scopes: ['insight:read', 'event:read', 'feature_flag:write', 'dashboard:read'],
    authorized_at: '2026-08-01T09:12:00Z',
    is_verified: false,
    is_first_party: false,
}

const passkey = {
    id: 'passkey-1',
    label: 'MacBook Pro',
    credential_id: 'credential-1',
    authenticator_type: 'platform',
    created_at: '2026-08-01T09:14:00Z',
    last_used_at: null,
    verified: true,
}

export const AllCredentialTypes: Story = {
    render: () => {
        useStorybookMocks({
            get: {
                '/_preflight': cloudPreflight,
                '/api/personal_api_keys': [partnerApiKey],
                '/api/webauthn/credentials/': [passkey],
                '/api/oauth/connected-apps/': [partnerApp],
            },
        })
        return <CredentialReview />
    },
}

export const OnlyAConnectedApplication: Story = {
    render: () => {
        useStorybookMocks({
            get: {
                '/_preflight': cloudPreflight,
                '/api/personal_api_keys': [],
                '/api/webauthn/credentials/': [],
                '/api/oauth/connected-apps/': [partnerApp],
            },
        })
        return <CredentialReview />
    },
}
