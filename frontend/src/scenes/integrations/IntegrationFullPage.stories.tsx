import { MOCK_DEFAULT_ORGANIZATION, MOCK_DEFAULT_TEAM } from 'lib/api.mock'

import { Meta, StoryObj } from '@storybook/react'

import { OrganizationMembershipLevel } from 'lib/constants'

import { mswDecorator } from '~/mocks/browser'
import preflightJson from '~/mocks/fixtures/_preflight.json'
import { mockIntegration } from '~/test/mocks'
import { Realm } from '~/types'

import { Slack } from './definitions'
import { IntegrationFullPage } from './IntegrationFullPage'

const meta: Meta<typeof IntegrationFullPage> = {
    title: 'Scenes-Other/Integration landing page',
    component: IntegrationFullPage,
    parameters: { layout: 'fullscreen', viewMode: 'story', mockDate: '2023-01-01' },
    decorators: [
        mswDecorator({
            get: {
                // slack_service.available drives whether the "Add to Slack" connect button shows
                '/_preflight': {
                    ...preflightJson,
                    realm: Realm.Cloud,
                    slack_service: { available: true, client_id: 'test-client-id' },
                },
            },
        }),
    ],
    render: () => <IntegrationFullPage definition={Slack} SettingsSection={Slack.SettingsSection} />,
}
export default meta

type Story = StoryObj<typeof IntegrationFullPage>

// integrationsLogic loads from the environments endpoint, not projects
export const NotConnected: Story = {
    decorators: [mswDecorator({ get: { '/api/environments/:id/integrations': { results: [] } } })],
}

export const Connected: Story = {
    decorators: [mswDecorator({ get: { '/api/environments/:id/integrations': { results: [mockIntegration] } } })],
}

const memberTeam = { ...MOCK_DEFAULT_TEAM, effective_membership_level: OrganizationMembershipLevel.Member }
const memberOrganization = {
    ...MOCK_DEFAULT_ORGANIZATION,
    membership_level: OrganizationMembershipLevel.Member,
    teams: [memberTeam],
}

// Below project-admin level: the connect button is replaced by the "request access" flow.
// `useRestrictedArea` reads the team's `effective_membership_level`, which teamLogic seeds from
// `getAppContext().current_team` (not an API call) — so we lower it in the app context here.
// `beforeEach` runs before Kea mounts teamLogic; the cleanup restores it for other stories.
// organizationLogic still fetches the org, so we mock that to Member too.
export const NoPermission: Story = {
    decorators: [
        mswDecorator({
            get: {
                '/api/environments/:id/integrations': { results: [] },
                '/api/organizations/@current/': memberOrganization,
            },
        }),
    ],
    beforeEach: () => {
        const appContext = window.POSTHOG_APP_CONTEXT
        const originalTeam = appContext?.current_team
        if (appContext) {
            appContext.current_team = memberTeam
        }
        return () => {
            if (appContext) {
                appContext.current_team = originalTeam ?? null
            }
        }
    },
}
