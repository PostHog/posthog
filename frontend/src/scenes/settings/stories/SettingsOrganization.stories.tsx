import { MOCK_DEFAULT_TEAM } from 'lib/api.mock'

import type { Meta, StoryObj } from '@storybook/react'
import { router } from 'kea-router'
import { useEffect } from 'react'

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
            },
            patch: {
                '/api/projects/:id': async (req, res, ctx) => {
                    // bounce the setting back as is
                    const newTeamSettings = { ...MOCK_DEFAULT_TEAM, ...(await req.json()) }
                    return res(ctx.json(newTeamSettings))
                },
            },
        }),
    ],
    render: ({ sectionId }: StoryProps) => {
        useEffect(() => {
            router.actions.push(urls.settings(sectionId))
        }, [sectionId])

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
