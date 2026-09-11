import type { Decorator, Meta, StoryObj } from '@storybook/react'
import { router } from 'kea-router'
import { useEffect } from 'react'

import { FEATURE_FLAGS } from 'lib/constants'
import { urls } from 'scenes/urls'

import { mswDecorator } from '~/mocks/browser'

import type { TicketPatternApi } from '../../generated/api.schemas'
import { SupportPatternsScene } from './SupportPatternsScene'

// Realistic but invented: two open patterns that need review and one already confirmed.

function makePattern(overrides: Partial<TicketPatternApi>): TicketPatternApi {
    return {
        id: '019f9582-93e7-77c1-8912-4f541d70cb13',
        topic: 'login password',
        source: 'terms',
        title: '9 tickets from 8 customers about: login password',
        summary: '',
        status: 'open',
        severity: 'medium',
        ticket_count: 9,
        requester_count: 8,
        peak_ticket_count: 9,
        first_ticket_at: '2026-07-25T09:12:00Z',
        opened_at: '2026-07-25T09:30:00Z',
        last_seen_at: '2026-07-25T10:15:00Z',
        resolved_at: null,
        resolved_by: null,
        owner: null,
        evidence: {},
        tickets: [
            {
                id: '019f9582-0000-7000-8000-000000000001',
                ticket_number: 4821,
                channel_source: 'email',
                email_subject: 'Cannot log in after password reset',
                status: 'open',
                created_at: '2026-07-25T09:12:00Z',
            },
            {
                id: '019f9582-0000-7000-8000-000000000002',
                ticket_number: 4823,
                channel_source: 'widget',
                email_subject: '',
                status: 'new',
                created_at: '2026-07-25T09:20:00Z',
            },
        ],
        ...overrides,
    }
}

const patterns: TicketPatternApi[] = [
    makePattern({}),
    makePattern({
        id: '019f9582-93e7-77c1-8912-4f541d70cb14',
        topic: 'export csv',
        title: '5 tickets from 5 customers about: export csv',
        ticket_count: 5,
        requester_count: 5,
        peak_ticket_count: 5,
        first_ticket_at: '2026-07-25T09:50:00Z',
        opened_at: '2026-07-25T10:00:00Z',
        tickets: [],
    }),
    makePattern({
        id: '019f9582-93e7-77c1-8912-4f541d70cb15',
        topic: 'webhook timeout',
        title: 'Webhook deliveries timing out',
        summary: 'Customers report outbound webhooks failing since the 08:40 deploy.',
        status: 'confirmed',
        severity: 'high',
        ticket_count: 14,
        requester_count: 12,
        peak_ticket_count: 14,
        first_ticket_at: '2026-07-24T08:41:00Z',
        opened_at: '2026-07-24T09:00:00Z',
        last_seen_at: '2026-07-24T11:30:00Z',
        resolved_at: '2026-07-24T09:05:00Z',
        tickets: [],
    }),
]

// The tabs read the active tab from the URL, so land on the patterns route like a real visit would.
const onPatternsRoute: Decorator = (Story) => {
    useEffect(() => {
        router.actions.push(urls.supportPatterns())
    }, [])
    return <Story />
}

const meta: Meta = {
    title: 'Scenes-App/Support/Patterns',
    component: SupportPatternsScene,
    parameters: {
        layout: 'fullscreen',
        viewMode: 'story',
        mockDate: '2026-07-25T10:20:00Z',
        featureFlags: [FEATURE_FLAGS.PRODUCT_SUPPORT_TICKET_PATTERNS],
    },
    decorators: [
        onPatternsRoute,
        mswDecorator({
            get: {
                '/api/projects/:id/conversations/patterns/': (req) => {
                    const status = new URL(req.request.url).searchParams.get('status')
                    const results = status ? patterns.filter((p) => status.split(',').includes(p.status)) : patterns
                    return [200, { results, count: results.length, next: null, previous: null }]
                },
            },
        }),
    ],
}
export default meta

type Story = StoryObj

export const NeedsReview: Story = {}

export const Narrow: Story = {
    render: () => (
        <div className="w-[520px]">
            <SupportPatternsScene />
        </div>
    ),
}

export const Empty: Story = {
    decorators: [
        mswDecorator({
            get: {
                '/api/projects/:id/conversations/patterns/': () => [
                    200,
                    { results: [], count: 0, next: null, previous: null },
                ],
            },
        }),
    ],
}
