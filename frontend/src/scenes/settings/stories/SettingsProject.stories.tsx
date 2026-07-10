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
            },
            patch: {
                '/api/projects/:id': async ({ request }) => {
                    // bounce the setting back as is
                    const newTeamSettings = { ...MOCK_DEFAULT_TEAM, ...((await request.json()) as object) }
                    return [200, newTeamSettings]
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

// -- Project --

export const SettingsProjectDetails: Story = { args: { sectionId: 'project-details' } }

export const SettingsProjectDangerZone: Story = { args: { sectionId: 'project-danger-zone' } }

// -- Project (legacy) --

export const SettingsProjectAutocapture: Story = { args: { sectionId: 'project-autocapture' } }

export const SettingsProjectProductAnalytics: Story = { args: { sectionId: 'project-product-analytics' } }

export const SettingsProjectReplay: Story = { args: { sectionId: 'project-replay' } }

export const SettingsProjectSurveys: Story = { args: { sectionId: 'project-surveys' } }

export const SettingsProjectIntegrations: Story = { args: { sectionId: 'project-integrations' } }

export const SettingsProjectAccessControl: Story = { args: { sectionId: 'project-access-control' } }
