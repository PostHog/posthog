import { MOCK_DEFAULT_TEAM } from 'lib/api.mock'

import { Meta, StoryObj } from '@storybook/react'
import { within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'

import { FEATURE_FLAGS } from 'lib/constants'
import { App } from 'scenes/App'
import { urls } from 'scenes/urls'

import { mswDecorator } from '~/mocks/browser'

import type { Ticket } from '../../types'

// Every name, address and message below is invented for the story.
function makeTicket(overrides: Partial<Ticket> & Pick<Ticket, 'id' | 'ticket_number'>): Ticket {
    return {
        distinct_id: `customer-${overrides.ticket_number}`,
        status: 'open',
        channel_source: 'widget',
        anonymous_traits: {},
        identity_verified: true,
        ai_resolved: false,
        created_at: '2026-11-10T09:00:00Z',
        updated_at: '2026-11-12T10:30:00Z',
        message_count: 3,
        last_message_at: '2026-11-12T10:30:00Z',
        last_message_text: null,
        unread_team_count: 0,
        unread_customer_count: 0,
        tags: [],
        ...overrides,
    }
}

const TICKETS: Ticket[] = [
    makeTicket({
        id: 'ticket-1042',
        ticket_number: 1042,
        priority: 'high',
        channel_source: 'email',
        email_to: 'help@example.com',
        anonymous_traits: { name: 'Avery Fernwood', email: 'avery@example.com' },
        last_message_text: 'The CSV export stops partway through when the table has more than a few thousand rows.',
        unread_team_count: 2,
        tags: ['billing', 'exports'],
        sla_due_at: '2026-11-12T12:40:00Z',
    }),
    makeTicket({
        id: 'ticket-1041',
        ticket_number: 1041,
        priority: 'medium',
        anonymous_traits: { name: 'Jordan Pebble', email: 'jordan@example.org' },
        identity_verified: false,
        last_message_text: 'Can I move the plan to another owner without losing the old invoices?',
        tags: ['billing'],
        updated_at: '2026-11-12T08:05:00Z',
    }),
    makeTicket({
        id: 'ticket-1039',
        ticket_number: 1039,
        priority: 'critical',
        channel_source: 'slack',
        channel_detail: 'slack_bot_mention',
        anonymous_traits: { name: 'Riley Quartz', email: 'riley@example.net' },
        last_message_text: 'Webhook deliveries time out since this morning.',
        unread_team_count: 1,
        sla_due_at: '2026-11-12T09:00:00Z',
        updated_at: '2026-11-11T17:45:00Z',
    }),
    makeTicket({
        id: 'ticket-1035',
        ticket_number: 1035,
        priority: 'low',
        anonymous_traits: { name: 'Sam Lantern', email: 'sam@example.com' },
        last_message_text: 'Thanks, the dashboard loads again. I will check it tomorrow too.',
        updated_at: '2026-11-10T15:20:00Z',
    }),
    makeTicket({
        id: 'ticket-1030',
        ticket_number: 1030,
        status: 'resolved',
        anonymous_traits: { name: 'Morgan Thistle', email: 'morgan@example.com' },
        last_message_text: 'Closing this one out. Reply here if it comes back.',
        updated_at: '2026-11-09T11:00:00Z',
    }),
]

function ticketsHandler(tickets: Ticket[]) {
    return ({ request }: { request: Request }) => {
        const params = new URL(request.url).searchParams
        // The setup check asks for one ticket. It must find one, or the scene shows its first-run state.
        if (params.get('limit') === '1') {
            return [200, { results: TICKETS.slice(0, 1), count: TICKETS.length }]
        }
        const statuses = params.get('status')?.split(',')
        const results = statuses ? tickets.filter((ticket) => statuses.includes(ticket.status)) : tickets
        return [200, { results, count: results.length }]
    }
}

const FILTERED_URL = `${urls.supportTickets()}?status=open&tags=billing`

const meta: Meta = {
    component: App,
    title: 'Scenes-App/Support/Tickets',
    parameters: {
        layout: 'fullscreen',
        viewMode: 'story',
        mockDate: '2026-11-12 11:00:00',
        pageUrl: FILTERED_URL,
        featureFlags: [FEATURE_FLAGS.TODAY_RAIL_NAV],
        testOptions: { waitForSelector: '[data-attr="ticket-applied-filter"]' },
    },
    decorators: [
        mswDecorator({
            get: {
                '/api/projects/:team_id/conversations/tickets/': ticketsHandler(TICKETS),
                '/api/projects/:team_id/conversations/tickets/unread_count/': { count: 3 },
                '/api/projects/:team_id/conversations/views/': { results: [], count: 0 },
                '/api/projects/:team_id/health_issues/summary/': {
                    unsnoozed: { total: 0, by_severity: {}, by_kind: {} },
                    snoozed: { total: 0, by_severity: {}, by_kind: {} },
                },
            },
            post: {
                '/api/projects/:team_id/file_system/home_folder/': { id: 'example-home', path: 'Home' },
            },
        }),
    ],
    // teamLogic seeds the team from the app context, not from a request, so support is turned on there.
    beforeEach: () => {
        const appContext = window.POSTHOG_APP_CONTEXT
        const originalTeam = appContext?.current_team
        if (appContext) {
            appContext.current_team = { ...MOCK_DEFAULT_TEAM, conversations_enabled: true }
        }
        return () => {
            if (appContext) {
                appContext.current_team = originalTeam ?? null
            }
        }
    },
}
export default meta

type Story = StoryObj<{}>

export const WithAppliedFilters: Story = {}

export const WithSelectedTickets: Story = {
    parameters: {
        pageUrl: urls.supportTickets(),
        testOptions: { waitForSelector: '[data-quill-inverted]' },
    },
    play: async ({ canvasElement }) => {
        const canvas = within(canvasElement)
        await userEvent.click(await canvas.findByLabelText('Select ticket 1042'))
        await userEvent.click(await canvas.findByLabelText('Select ticket 1039'))
    },
}

export const NarrowScene: Story = {
    parameters: {
        testOptions: {
            waitForSelector: '[data-attr="ticket-applied-filter"]',
            viewport: { width: 600, height: 900 },
        },
    },
}

export const NoMatchingTickets: Story = {
    decorators: [
        mswDecorator({
            get: {
                '/api/projects/:team_id/conversations/tickets/': ticketsHandler([]),
            },
        }),
    ],
    parameters: {
        testOptions: { waitForSelector: 'text=No tickets' },
    },
}
