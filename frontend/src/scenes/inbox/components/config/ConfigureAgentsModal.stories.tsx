import type { Meta, StoryObj } from '@storybook/react'
import { useActions } from 'kea'
import { useEffect } from 'react'

import { mswDecorator } from '~/mocks/browser'

import { mockAutonomy, mockReviewers, mockSourceConfigs } from '../../__mocks__/inboxMocks'
import { signalSourcesLogic } from '../../signalSourcesLogic'
import { ConfigureAgentsModal } from './ConfigureAgentsModal'

// The "Configure agents" modal, opened. Polish the section layout (Connections /
// Agents / Slack / Auto-start / MCP) against the desktop Agents view.

function OpenConfigureAgents(): JSX.Element {
    const { openSourcesModal } = useActions(signalSourcesLogic)
    useEffect(() => {
        openSourcesModal()
    }, [openSourcesModal])
    return <ConfigureAgentsModal />
}

const meta: Meta = {
    title: 'Scenes-App/Inbox/Configure agents',
    parameters: { layout: 'fullscreen', viewMode: 'story', mockDate: '2026-06-11' },
    decorators: [
        mswDecorator({
            get: {
                '/api/projects/:id/signals/source_configs': () => [200, mockSourceConfigs],
                '/api/projects/:id/signals/reports/available_reviewers': () => [200, mockReviewers],
                '/api/projects/:id/integrations': () => [
                    200,
                    {
                        results: [
                            {
                                id: 1,
                                kind: 'github',
                                config: { account: { name: 'PostHog' } },
                                created_at: '2026-06-10T12:00:00Z',
                                created_by: null,
                            },
                        ],
                        count: 1,
                    },
                ],
                '/api/users/@me/signal_autonomy': () => [200, mockAutonomy],
                '/api/projects/:id/external_data_sources': () => [200, { results: [], count: 0 }],
                '/api/projects/:id/external_data_sources/': () => [200, { results: [], count: 0 }],
            },
        }),
    ],
    render: () => <OpenConfigureAgents />,
}
export default meta

type Story = StoryObj
export const Default: Story = {}
