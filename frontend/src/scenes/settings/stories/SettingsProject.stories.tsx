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
