import { MOCK_DEFAULT_TEAM } from 'lib/api.mock'

import type { Decorator, Meta, StoryObj } from '@storybook/react'
import { router } from 'kea-router'
import { useEffect } from 'react'

import { FEATURE_FLAGS } from 'lib/constants'
import { teamLogic } from 'scenes/teamLogic'
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
// The Patterns tab itself only shows once detection is on, and the bootstrap team has it off.
const onPatternsRoute: Decorator = (Story) => {
    useEffect(() => {
        teamLogic.actions.loadCurrentTeamSuccess({
            ...MOCK_DEFAULT_TEAM,
            conversations_enabled: true,
            conversations_settings: { pattern_detection_enabled: true },
        })
        router.actions.push(urls.supportPatterns())
    }, [])
    return <Story />
}

// Invented scan findings: what the hourly scout would file beside the detector's own patterns.
const aiScanOn = {
    enabled: true,
    scout_config_id: '019f9582-0000-7000-8000-0000000000c1',
    skill_name: 'signals-scout-ticket-patterns',
    last_run_at: '2026-07-25T10:02:00Z',
    ai_consent_granted: true,
}

const aiScanReports = [
    {
        report_id: '019f9582-0000-7000-8000-0000000000d1',
        title: 'Exports stall for accounts on the EU region since 09:30',
        summary:
            'Four customers on four different domains describe the same stall in different words.\n\n' +
            'All four sit on the EU region, and the open "export" pattern from the detector holds only one of them. ' +
            'Tickets: [#4182](/support/tickets/019f9582-0000-7000-8000-0000000000e1), ' +
            '[#4190](/support/tickets/019f9582-0000-7000-8000-0000000000e2), ' +
            '[#4203](/support/tickets/019f9582-0000-7000-8000-0000000000e3), ' +
            '[#4211](/support/tickets/019f9582-0000-7000-8000-0000000000e4).',
        filed_at: '2026-07-25T10:02:00Z',
    },
    {
        report_id: '019f9582-0000-7000-8000-0000000000d2',
        title: 'Magic link emails arrive late for three customers',
        summary:
            'None of the three tickets share a word the detector matches on, but each describes a 20 minute delay.\n\n' +
            'Tickets: [#4176](/support/tickets/019f9582-0000-7000-8000-0000000000e5), ' +
            '[#4181](/support/tickets/019f9582-0000-7000-8000-0000000000e6), ' +
            '[#4188](/support/tickets/019f9582-0000-7000-8000-0000000000e7).',
        filed_at: '2026-07-25T09:02:00Z',
    },
]

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
                '/api/projects/:id/conversations/pattern_ai_scan/status/': () => [200, aiScanOn],
                '/api/projects/:id/conversations/pattern_ai_scan/reports/': () => [200, aiScanReports],
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

// The narrow layout only holds if long text truncates, so give it a pattern whose title, summary
// and evidence subject each run past the column.
const longPattern = makePattern({
    id: '019f9582-93e7-77c1-8912-4f541d70cb16',
    topic: 'scheduled export',
    title: '11 tickets from 9 customers about: scheduled export to the reporting warehouse fails overnight',
    summary:
        'Every overnight run since Tuesday stops at the same step, and the job page at https://example.com/settings/integrations/warehouse-exports/scheduled/overnight shows no error.',
    ticket_count: 11,
    requester_count: 9,
    peak_ticket_count: 11,
    tickets: [
        {
            id: '019f9582-0000-7000-8000-000000000009',
            ticket_number: 4907,
            channel_source: 'email',
            email_subject: 'Scheduled export to the reporting warehouse failed again overnight with no alert',
            status: 'open',
            created_at: '2026-07-25T09:40:00Z',
        },
    ],
})

export const NarrowLongText: Story = {
    decorators: [
        mswDecorator({
            get: {
                '/api/projects/:id/conversations/patterns/': () => [
                    200,
                    { results: [longPattern], count: 1, next: null, previous: null },
                ],
            },
        }),
    ],
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

// A paused scout keeps its section so its old findings stay reachable, but says the scan is off.
export const AiScanPaused: Story = {
    decorators: [
        mswDecorator({
            get: {
                '/api/projects/:id/conversations/pattern_ai_scan/status/': () => [200, { ...aiScanOn, enabled: false }],
                '/api/projects/:id/conversations/pattern_ai_scan/reports/': () => [200, []],
            },
        }),
    ],
}
