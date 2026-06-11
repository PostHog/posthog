import type { Meta, StoryObj } from '@storybook/react'

import { mswDecorator } from '~/mocks/browser'

import { mockAutonomy, mockReviewers, mockSourceConfigs } from '../../__mocks__/inboxMocks'
import { AgentsTab } from './AgentsTab'

// The "Agents" tab — full-page high-fidelity port of the desktop Agents view
// (Connections / Agents roster / Slack / Auto-start / MCP servers).

const meta: Meta = {
    title: 'Scenes-App/Inbox/Agents tab',
    component: AgentsTab,
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
    render: () => (
        <div className="bg-primary min-h-screen">
            <AgentsTab />
        </div>
    ),
}
export default meta

type Story = StoryObj
export const Default: Story = {}
