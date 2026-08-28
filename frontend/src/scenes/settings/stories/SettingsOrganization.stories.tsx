import { MOCK_DEFAULT_TEAM } from 'lib/api.mock'

import type { Meta, StoryObj } from '@storybook/react'
import { router } from 'kea-router'

import { STORYBOOK_FEATURE_FLAGS } from 'lib/constants'
import { App } from 'scenes/App'
import { urls } from 'scenes/urls'

import { mswDecorator } from '~/mocks/browser'
import preflightJson from '~/mocks/fixtures/_preflight.json'

import { SettingSectionId } from '../types'

interface StoryProps {
    sectionId: SettingSectionId
}

type Story = StoryObj<(props: StoryProps) => JSX.Element>
const meta: Meta<(props: StoryProps) => JSX.Element> = {
    title: 'Scenes-App/Settings/Organization',
    parameters: {
        layout: 'fullscreen',
        viewMode: 'story',
        mockDate: '2023-05-25',
        featureFlags: STORYBOOK_FEATURE_FLAGS,
    },
    decorators: [
        mswDecorator({
            get: {
                '/_preflight': {
                    ...preflightJson,
                    cloud: true,
                    realm: 'cloud',
                },
                '/api/projects/:id/integrations': { results: [] },
                '/api/organizations/:id/integrations': { results: [] },
                // One member with a rule already saved and one without, so the member
                // notifications section renders both states of the control.
                '/api/organizations/:id/notification_locks/': [
                    {
                        user_id: 1,
                        uuid: '0198aaaa-0000-4000-8000-000000000001',
                        first_name: 'Ada',
                        last_name: 'Kowalski',
                        email: 'ada@example.com',
                        organization_membership_level: 1,
                        editable: true,
                        locks: [
                            {
                                setting: 'pipeline_notifications_disabled',
                                scope_id: String(MOCK_DEFAULT_TEAM.id),
                                locked_value: false,
                            },
                        ],
                    },
                    {
                        user_id: 2,
                        uuid: '0198aaaa-0000-4000-8000-000000000002',
                        first_name: 'Grace',
                        last_name: 'Osei',
                        email: 'grace@example.com',
                        organization_membership_level: 15,
                        editable: false,
                        locks: [],
                    },
                ],
                '/api/organizations/:organization_id/desktop_beta_terms/': {
                    is_desktop_beta_terms_accepted: false,
                },
                '/api/environments/:team_id/conversations/': { results: [] },
                '/api/user_home_settings/@me/': {},
                '/api/organizations/:organization_id/proxy_records': {
                    results: [
                        {
                            id: 'proxy-1',
                            domain: 't.example.com',
                            status: 'valid',
                            target_cname: 't-example-com.proxy.posthog.cc',
                        },
                    ],
                    max_proxy_records: 2,
                },
                // One bound token and one left over from before URL binding, so the story
                // covers the warning banner and the "Not verifying" cell as well as the
                // ordinary row.
                '/api/organizations/:organization_id/cimd_verification_tokens/': {
                    count: 2,
                    next: null,
                    previous: null,
                    results: [
                        {
                            id: 'b7d3a1c2-0000-4000-8000-000000000001',
                            label: 'Production CIMD partner',
                            cimd_url: 'https://partner.example.com/.well-known/oauth-client-metadata.json',
                            mask_value: 'phvt...4f2a',
                            created_by: null,
                            created_at: '2023-05-20T10:00:00Z',
                            last_used_at: '2023-05-24T18:30:00Z',
                        },
                        {
                            id: 'b7d3a1c2-0000-4000-8000-000000000002',
                            label: 'Legacy token',
                            cimd_url: null,
                            mask_value: 'phvt...9c11',
                            created_by: null,
                            created_at: '2023-04-02T09:15:00Z',
                            last_used_at: null,
                        },
                    ],
                },
            },
            patch: {
                '/api/projects/:id': async ({ request }) => {
                    // bounce the setting back as is
                    const newTeamSettings = { ...MOCK_DEFAULT_TEAM, ...((await request.json()) as object) }
                    return [200, newTeamSettings]
                },
            },
            post: {
                '/api/organizations/:organization_id/desktop_beta_terms/': {
                    is_desktop_beta_terms_accepted: true,
                },
            },
        }),
    ],
    render: ({ sectionId }: StoryProps) => {
        // Navigate synchronously before <App /> mounts so it renders the settings scene directly,
        // never the project homepage. A useEffect push fires after the first paint, so the snapshot
        // can race and capture the homepage frame instead.
        router.actions.push(urls.settings(sectionId))

        return <App />
    },
}
export default meta

// -- Organization --

export const SettingsOrganizationDetails: Story = { args: { sectionId: 'organization-details' } }

export const SettingsOrganizationMembers: Story = { args: { sectionId: 'organization-members' } }

export const SettingsOrganizationRoles: Story = { args: { sectionId: 'organization-roles' } }

export const SettingsOrganizationAuthentication: Story = { args: { sectionId: 'organization-authentication' } }

export const SettingsOrganizationProxy: Story = { args: { sectionId: 'organization-proxy' } }

export const SettingsOrganizationDangerZone: Story = { args: { sectionId: 'organization-danger-zone' } }

export const SettingsOrganizationBilling: Story = { args: { sectionId: 'organization-billing' } }

export const SettingsOrganizationStartupProgram: Story = { args: { sectionId: 'organization-startup-program' } }

export const SettingsOrganizationCimdVerificationTokens: Story = {
    args: { sectionId: 'organization-cimd-verification-tokens' },
}
