import { MOCK_DEFAULT_ORGANIZATION } from 'lib/api.mock'

import { Meta, StoryObj } from '@storybook/react'

import { ApiConfig } from 'lib/api'

import { useStorybookMocks } from '~/mocks/browser'

import { OAuthApps } from './OAuthApps'

const meta: Meta = {
    title: 'Scenes-Other/Settings/Organization/OAuth Apps',
    component: OAuthApps,
}
export default meta

type Story = StoryObj<{}>

const ACME = {
    id: '1',
    name: 'Acme Analytics',
    client_id: 'abc123def456ghi789',
    redirect_uris_list: ['https://acme.example.com/callback'],
    is_verified: true,
    is_cimd_client: false,
    provisioning_status: 'not_a_partner',
    provisioning_review: null,
    created: '2025-11-01T10:30:00Z',
    updated: '2025-11-01T10:30:00Z',
}

const PARTNER_WAITING_FOR_STAFF = {
    id: '2',
    name: 'Example Builder',
    client_id: 'https://builder.example.com/.well-known/posthog-client.json',
    redirect_uris_list: ['https://builder.example.com/callback'],
    is_verified: false,
    is_cimd_client: true,
    provisioning_status: 'waiting_for_staff',
    provisioning_review: {
        status: 'needs_human',
        opened_at: '2025-12-15T14:00:00Z',
        decided_at: '2025-12-15T14:04:00Z',
        partner_message: "We couldn't find a homepage for this application. Add client_uri to your metadata document.",
        timeline: [
            { at: '2025-12-15T14:00:00Z', kind: 'registered', status: null, message: '', author: '' },
            { at: '2025-12-15T14:04:00Z', kind: 'automated_review', status: 'needs_human', message: '', author: '' },
        ],
    },
    created: '2025-12-15T14:00:00Z',
    updated: '2025-12-15T14:04:00Z',
}

const PARTNER_ON = {
    id: '3',
    name: 'Example Agents',
    client_id: 'https://agents.example.com/.well-known/posthog-client.json',
    redirect_uris_list: ['https://agents.example.com/callback'],
    is_verified: true,
    is_cimd_client: true,
    provisioning_status: 'on',
    provisioning_review: {
        status: 'accepted',
        opened_at: '2025-12-01T09:00:00Z',
        decided_at: '2025-12-01T09:02:00Z',
        partner_message: '',
        timeline: [
            { at: '2025-12-01T09:00:00Z', kind: 'registered', status: null, message: '', author: '' },
            { at: '2025-12-01T09:02:00Z', kind: 'automated_review', status: 'accepted', message: '', author: '' },
        ],
    },
    created: '2025-12-01T09:00:00Z',
    updated: '2025-12-01T09:02:00Z',
}

function mockApps(results: object[]): void {
    // The app knows the organization before any settings page mounts. A story starts without one.
    ApiConfig.setCurrentOrganizationId(MOCK_DEFAULT_ORGANIZATION.id)
    useStorybookMocks({
        get: {
            '/api/organizations/:organization_id/oauth_applications/': {
                count: results.length,
                next: null,
                previous: null,
                results,
            },
        },
    })
}

export const Empty: Story = {
    render: () => {
        mockApps([])
        return <OAuthApps />
    },
}

export const WithApps: Story = {
    parameters: {
        testOptions: { waitForSelector: '[data-attr="oauth-app-open"]' },
    },
    render: () => {
        mockApps([ACME, PARTNER_WAITING_FOR_STAFF, PARTNER_ON])
        return <OAuthApps />
    },
}
