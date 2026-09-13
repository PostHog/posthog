import { MOCK_DEFAULT_TEAM } from 'lib/api.mock'

import type { Decorator, Meta, StoryObj } from '@storybook/react'
import { useEffect } from 'react'

import { FEATURE_FLAGS } from 'lib/constants'
import { teamLogic } from 'scenes/teamLogic'

import { mswDecorator } from '~/mocks/browser'

import { TicketPatternsSection } from './TicketPatternsSection'

// Invented overrides: a muted newsletter topic and a watched data-loss topic.

const overrides = [
    {
        id: '019f9582-0000-7000-8000-000000000101',
        kind: 'mute',
        topic: 'weekly digest',
        notes: '',
        enabled: true,
        created_by: null,
        created_at: '2026-07-20T09:00:00Z',
    },
    {
        id: '019f9582-0000-7000-8000-000000000102',
        kind: 'watch',
        topic: 'data loss',
        notes: '',
        enabled: true,
        created_by: null,
        created_at: '2026-07-21T09:00:00Z',
    },
]

const meta: Meta = {
    title: 'Scenes-App/Support/Settings/TicketPatterns',
    component: TicketPatternsSection,
    parameters: {
        layout: 'padded',
        viewMode: 'story',
        mockDate: '2026-07-25T10:20:00Z',
        featureFlags: [FEATURE_FLAGS.PRODUCT_SUPPORT_TICKET_PATTERNS],
    },
    decorators: [
        mswDecorator({
            get: {
                '/api/projects/:id/conversations/pattern_overrides/': () => [
                    200,
                    { results: overrides, count: overrides.length, next: null, previous: null },
                ],
                '/api/organizations/:id/roles/': () => [
                    200,
                    {
                        results: [
                            { id: '11111111-1111-1111-1111-111111111111', name: 'Support engineers', members: [] },
                        ],
                    },
                ],
            },
        }),
    ],
}
export default meta

type Story = StoryObj

const ENABLED_TEAM = {
    ...MOCK_DEFAULT_TEAM,
    conversations_enabled: true,
    conversations_settings: {
        pattern_detection_enabled: true,
        pattern_min_requesters: 5,
        pattern_min_tickets: 5,
        pattern_window_minutes: 60,
        pattern_notify_role_id: '11111111-1111-1111-1111-111111111111',
    },
}

// The section reads its state from teamLogic, and the bootstrap mocks resolve before a story's own
// handlers register, so the enabled state is loaded into the logic directly.
const withPatternsEnabled: Decorator = (Story) => {
    useEffect(() => {
        teamLogic.actions.loadCurrentTeamSuccess(ENABLED_TEAM)
    }, [])
    return <Story />
}

export const Enabled: Story = {
    decorators: [withPatternsEnabled],
}

export const Narrow: Story = {
    ...Enabled,
    render: () => (
        <div className="w-[520px]">
            <TicketPatternsSection />
        </div>
    ),
}

export const Disabled: Story = {}
