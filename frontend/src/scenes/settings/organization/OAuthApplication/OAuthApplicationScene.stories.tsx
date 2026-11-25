import { Meta, StoryObj } from '@storybook/react'

import { FEATURE_FLAGS, STORYBOOK_FEATURE_FLAGS } from 'lib/constants'
import { App } from 'scenes/App'
import { urls } from 'scenes/urls'

import { mswDecorator } from '~/mocks/browser'
import preflightJson from '~/mocks/fixtures/_preflight.json'

const STAFF_MESSAGE = 'Tell us how people sign up through your product, and who to contact about abuse reports.'

const METADATA_DOCUMENT = {
    client_id: 'https://studio.example.com/.well-known/posthog-client.json',
    client_name: 'Example Studio',
    client_uri: 'https://studio.example.com',
    logo_uri: 'https://studio.example.com/logo.png',
    policy_uri: 'https://studio.example.com/privacy',
    contacts: ['security@studio.example.com'],
    redirect_uris: ['https://studio.example.com/callback'],
    token_endpoint_auth_method: 'private_key_jwt',
    jwks_uri: 'https://studio.example.com/.well-known/jwks.json',
    'com.posthog': { provisioning: true },
}

const ANSWERED = {
    id: 'oauth-app-1',
    name: 'Example Studio',
    client_id: METADATA_DOCUMENT.client_id,
    redirect_uris_list: METADATA_DOCUMENT.redirect_uris,
    is_verified: false,
    is_cimd_client: true,
    provisioning_status: 'waiting_for_staff',
    provisioning_review: {
        status: 'needs_human',
        opened_at: '2026-01-10T11:00:00Z',
        decided_at: null,
        partner_message: STAFF_MESSAGE,
        timeline: [
            { at: '2026-01-10T11:00:00Z', kind: 'registered', status: null, message: '', author: '' },
            { at: '2026-01-10T11:03:00Z', kind: 'automated_review', status: 'needs_human', message: '', author: '' },
            {
                at: '2026-01-11T16:20:00Z',
                kind: 'staff_decision',
                status: 'changes_requested',
                message: STAFF_MESSAGE,
                author: '',
            },
            {
                at: '2026-01-12T09:15:00Z',
                kind: 'partner_note',
                status: null,
                message: 'People sign up from our onboarding page. Abuse reports go to security@studio.example.com.',
                author: 'admin@studio.example.com',
            },
        ],
    },
    registration: {
        client_name: METADATA_DOCUMENT.client_name,
        client_uri: METADATA_DOCUMENT.client_uri,
        logo_uri: METADATA_DOCUMENT.logo_uri,
        tos_uri: '',
        policy_uri: METADATA_DOCUMENT.policy_uri,
        contacts: METADATA_DOCUMENT.contacts,
        redirect_uris: METADATA_DOCUMENT.redirect_uris,
        jwks_uri: METADATA_DOCUMENT.jwks_uri,
        authentication: 'private_key_jwt',
        scopes: ['organization:read', 'project:write'],
        uses_default_scopes: false,
        needs_signing_key: false,
        can_create_accounts: true,
        can_provision_resources: true,
        organization_link: 'this_organization',
        metadata_document: JSON.stringify(METADATA_DOCUMENT, null, 2),
    },
    created: '2026-01-10T11:00:00Z',
    updated: '2026-01-12T09:15:00Z',
}

const DECLINED = {
    ...ANSWERED,
    registration: {
        ...ANSWERED.registration,
        scopes: ['action:read', 'dashboard:read', 'insight:read', 'insight:write', 'project:read'],
        uses_default_scopes: true,
        authentication: 'none',
        jwks_uri: '',
        needs_signing_key: true,
    },
    provisioning_status: 'declined',
    provisioning_review: {
        ...ANSWERED.provisioning_review,
        status: 'declined',
        decided_at: '2026-01-11T16:20:00Z',
        timeline: [
            ...ANSWERED.provisioning_review.timeline.slice(0, 2),
            {
                at: '2026-01-11T16:20:00Z',
                kind: 'staff_decision',
                status: 'declined',
                message: STAFF_MESSAGE,
                author: '',
            },
        ],
    },
}

function scene(application: object): Partial<Meta> {
    return {
        decorators: [
            mswDecorator({
                get: {
                    '/_preflight': { ...preflightJson, cloud: true, realm: 'cloud' },
                    '/api/organizations/:id/oauth_applications/': {
                        count: 1,
                        next: null,
                        previous: null,
                        results: [application],
                    },
                    '/api/organizations/:id/oauth_applications/:appId/': application,
                    '/api/projects/:id/wizard/scans/detected_sources/': [],
                    '/api/projects/:id/notifications/': { results: [] },
                    '/api/projects/:id/notifications/unread_count/': { count: 0 },
                    '/api/projects/:id/wizard/runs/': { count: 0, results: [] },
                },
                post: {
                    '/api/projects/:id/file_system/home_folder/': { id: 'home', path: 'Users/Example' },
                },
            }),
        ],
    }
}

type Story = StoryObj<{}>
const meta: Meta = {
    title: 'Scenes-App/Settings/OAuth application',
    component: App,
    parameters: {
        layout: 'fullscreen',
        viewMode: 'story',
        mockDate: '2026-01-15',
        pageUrl: urls.oauthApplication(ANSWERED.id),
        featureFlags: STORYBOOK_FEATURE_FLAGS,
        testOptions: { waitForSelector: '[data-attr="oauth-app-review-note-preview"]', snapshotBrowsers: [] },
    },
}
export default meta

export const AnsweredAndWaitingForStaff: Story = { ...scene(ANSWERED) }

export const Declined: Story = { ...scene(DECLINED) }

export const AnsweredAndWaitingForStaffNewUI: Story = {
    ...scene(ANSWERED),
    parameters: { featureFlags: [...STORYBOOK_FEATURE_FLAGS, FEATURE_FLAGS.TODAY_RAIL_NAV] },
}
