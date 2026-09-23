import { Meta, StoryObj } from '@storybook/react'
import { useActions } from 'kea'
import { useEffect } from 'react'

import { FEATURE_FLAGS } from 'lib/constants'

import { mswDecorator } from '~/mocks/browser'

import { composerSeedLogic } from 'products/posthog_ai/frontend/api/logics'

import { AiFirstMaxInstance } from './components/AiFirstMaxInstance'
import { MAX_SIDE_PANEL_ID } from './components/PhaiSidePanelChat'
import { MaxInstance } from './Max'
import { maxGlobalLogic } from './maxGlobalLogic'
import { sharedMeta } from './maxStoriesShared'

function AccessStory({ sidePanel = false }: { sidePanel?: boolean }): JSX.Element {
    const { setPhaiViewMode } = useActions(maxGlobalLogic)
    const { setSeed } = useActions(composerSeedLogic({ panelId: sidePanel ? MAX_SIDE_PANEL_ID : undefined }))

    useEffect(() => {
        setPhaiViewMode('new')
        setSeed({ prompt: 'Explain the example chart', autoSubmit: false })
    }, [setPhaiViewMode, setSeed])

    return (
        <div className="h-screen max-w-5xl mx-auto">
            {sidePanel ? <MaxInstance sidePanel /> : <AiFirstMaxInstance tabId="access-story" />}
        </div>
    )
}

const meta: Meta<typeof AccessStory> = {
    ...sharedMeta,
    title: 'Scenes-App/PostHog AI access',
    component: AccessStory,
    parameters: {
        ...sharedMeta.parameters,
        featureFlags: [FEATURE_FLAGS.TASKS, FEATURE_FLAGS.PHAI_SANDBOX_MODE],
    },
    decorators: [
        ...[sharedMeta.decorators ?? []].flat(),
        mswDecorator({
            get: {
                '/api/projects/:team_id/desktop/access/': { allowed: false, reason: 'startup_plan' },
                '/api/projects/:team_id/tasks/': { results: [], count: 0 },
                '/api/projects/:team_id/tasks/repositories/': { repositories: [] },
                '/api/projects/:team_id/integrations/': { results: [] },
            },
        }),
    ],
}
export default meta
type Story = StoryObj<typeof meta>

export const StartupCredits: Story = {}

export const PrepaidCredits: Story = {
    decorators: [
        mswDecorator({
            get: {
                '/api/projects/:team_id/desktop/access/': { allowed: false, reason: 'prepaid_credits' },
            },
        }),
    ],
}

export const SidePanel: Story = {
    args: { sidePanel: true },
}
