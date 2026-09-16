import { MOCK_DEFAULT_TEAM } from 'lib/api.mock'

import type { Meta, StoryObj } from '@storybook/react'
import { router } from 'kea-router'

import { FEATURE_FLAGS, STORYBOOK_FEATURE_FLAGS, OrganizationMembershipLevel } from 'lib/constants'
import { App } from 'scenes/App'
import { teamLogic } from 'scenes/teamLogic'
import { urls } from 'scenes/urls'

import { mswDecorator } from '~/mocks/browser'
import preflightJson from '~/mocks/fixtures/_preflight.json'
import { AccessControlLevel, AccessControlResourceType } from '~/types'

import { SettingSectionId } from '../types'

interface StoryProps {
    sectionId: SettingSectionId
}

type Story = StoryObj<(props: StoryProps) => JSX.Element>
const meta: Meta<(props: StoryProps) => JSX.Element> = {
    title: 'Scenes-App/Settings/Project',
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
                // The GitHub section fetches both on mount; unmocked, their error toasts land in the snapshot.
                '/api/projects/:id/integrations/github/available_installations/': {
                    installations: [],
                    personal_github_connected: false,
                },
                '/api/users/@me/integrations/github/install_requests/': { results: [], install_url: null },
                // The tags field autocompletes from this; unmocked, its error toast lands in the snapshot.
                '/api/projects/:id/tags': ['eu-region', 'production'],
            },
            patch: {
                // bounce the setting back as is. `updateCurrentTeam` patches the environment for
                // everything except a bare project rename, so both routes need a handler.
                '/api/projects/:id': async ({ request }) => [
                    200,
                    { ...MOCK_DEFAULT_TEAM, ...((await request.json()) as object) },
                ],
                '/api/environments/:id': async ({ request }) => [
                    200,
                    { ...MOCK_DEFAULT_TEAM, ...((await request.json()) as object) },
                ],
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

// -- Project --

export const SettingsProjectDetails: Story = { args: { sectionId: 'project-details' } }

export const SettingsProjectCustomization: Story = { args: { sectionId: 'project-customization' } }

export const SettingsProjectDangerZone: Story = { args: { sectionId: 'project-danger-zone' } }

// -- Project (legacy) --

export const SettingsProjectAutocapture: Story = { args: { sectionId: 'project-autocapture' } }

export const SettingsProjectProductAnalytics: Story = { args: { sectionId: 'project-product-analytics' } }

export const SettingsProjectReplay: Story = { args: { sectionId: 'project-replay' } }

export const SettingsProjectSurveys: Story = { args: { sectionId: 'project-surveys' } }

export const SettingsProjectIntegrations: Story = { args: { sectionId: 'project-integrations' } }

export const SettingsProjectAccessControl: Story = { args: { sectionId: 'project-access-control' } }

export const SettingsProjectLogs: Story = {
    args: { sectionId: 'project-logs' },
    parameters: { featureFlags: [] },
    decorators: [
        mswDecorator({
            get: {
                '/api/projects/:id/logs/sampling_rules/': { results: [] },
                '/api/projects/:id/logs/alerts/': { results: [] },
                '/api/projects/:id/logs_config/': {
                    logs_distinct_id_attribute_key: 'posthogDistinctId',
                    logs_distinct_id_attribute_keys: ['posthogDistinctId'],
                    logs_session_id_attribute_keys: ['sessionId'],
                    logs_pattern_message_keys: ['message', 'msg', 'event'],
                },
            },
            patch: {
                '/api/projects/:id/logs_config/': async ({ request }) => [
                    200,
                    {
                        logs_distinct_id_attribute_key: 'posthogDistinctId',
                        logs_distinct_id_attribute_keys: ['posthogDistinctId'],
                        logs_session_id_attribute_keys: ['sessionId'],
                        ...((await request.json()) as object),
                    },
                ],
            },
        }),
    ],
}

export const SettingsProjectLogsReadOnly: Story = {
    ...SettingsProjectLogs,
    render: ({ sectionId }) => {
        teamLogic.actions.loadCurrentTeamSuccess({
            ...MOCK_DEFAULT_TEAM,
            effective_membership_level: OrganizationMembershipLevel.Member,
        })
        router.actions.push(urls.settings(sectionId))
        return <App />
    },
}

export const SettingsProjectLogsJsonParsing: Story = {
    ...SettingsProjectLogs,
    parameters: {
        featureFlags: [FEATURE_FLAGS.LOGS_SETTINGS_JSON, FEATURE_FLAGS.LOGS_JSON_ATTRIBUTE_PARSING],
    },
    beforeEach: () => {
        const appContext = window.POSTHOG_APP_CONTEXT
        if (!appContext) {
            return
        }
        const originalAccess = appContext.resource_access_control
        appContext.resource_access_control = {
            ...originalAccess,
            [AccessControlResourceType.Logs]: AccessControlLevel.Manager,
        }
        return () => {
            appContext.resource_access_control = originalAccess
        }
    },
}

export const SettingsProjectLogsJsonParsingReadOnly: Story = {
    ...SettingsProjectLogsJsonParsing,
    render: SettingsProjectLogsReadOnly.render,
}

export const SettingsProjectLogsJsonParsingFlagOff: Story = {
    ...SettingsProjectLogsJsonParsing,
    parameters: { featureFlags: [FEATURE_FLAGS.LOGS_SETTINGS_JSON] },
}
