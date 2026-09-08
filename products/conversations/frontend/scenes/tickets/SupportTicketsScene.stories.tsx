import { MOCK_DEFAULT_TEAM } from 'lib/api.mock'

import { Meta, StoryObj } from '@storybook/react'

import { App } from 'scenes/App'
import { urls } from 'scenes/urls'

import { mswDecorator } from '~/mocks/browser'
import { toPaginatedResponse } from '~/mocks/handlers'

import type { SavedTicketView, Ticket } from '../../types'

function mockTicket(overrides: Partial<Ticket> & Pick<Ticket, 'id' | 'ticket_number' | 'last_message_text'>): Ticket {
    return {
        distinct_id: `distinct-${overrides.ticket_number}`,
        status: 'open',
        channel_source: 'email',
        anonymous_traits: { email: `person-${overrides.ticket_number}@example.com` },
        identity_verified: false,
        ai_resolved: false,
        created_at: '2026-06-14T09:00:00Z',
        updated_at: '2026-06-15T08:30:00Z',
        message_count: 2,
        last_message_at: '2026-06-15T08:30:00Z',
        unread_team_count: 0,
        unread_customer_count: 0,
        ...overrides,
    }
}

const MOCK_TICKETS: Ticket[] = [
    mockTicket({
        id: 'ticket-1',
        ticket_number: 4821,
        last_message_text: 'The CSV export stops at 10,000 rows even though the insight has more',
        priority: 'high',
        unread_team_count: 1,
        updated_at: '2026-06-15T08:48:00Z',
    }),
    mockTicket({
        id: 'ticket-2',
        ticket_number: 4819,
        last_message_text: 'Session replay shows a blank screen on our checkout page',
        channel_source: 'widget',
        unread_team_count: 1,
        updated_at: '2026-06-15T08:20:00Z',
    }),
    mockTicket({
        id: 'ticket-3',
        ticket_number: 4815,
        last_message_text: 'Can we get an invoice with our VAT number on it?',
        status: 'pending',
        priority: 'low',
        updated_at: '2026-06-15T05:00:00Z',
    }),
    mockTicket({
        id: 'ticket-4',
        ticket_number: 4808,
        last_message_text: 'Thanks, that fixed it!',
        status: 'resolved',
        channel_source: 'widget',
        updated_at: '2026-06-14T16:00:00Z',
    }),
]

function mockView(short_id: string, name: string, filters: SavedTicketView['filters']): SavedTicketView {
    return {
        id: `view-${short_id}`,
        short_id,
        name,
        filters,
        created_at: '2026-06-01T10:00:00Z',
        created_by: null,
        is_favorited: true,
    }
}

const MOCK_VIEWS: SavedTicketView[] = [
    mockView('open', 'Open', { status: ['open'] }),
    mockView('mine', 'Mine', { assignee: ['me'] }),
    mockView('slarisk', 'SLA at risk', { sla: 'at-risk' }),
]

const meta: Meta = {
    component: App,
    title: 'Scenes-App/Support',
    parameters: {
        layout: 'fullscreen',
        viewMode: 'story',
        mockDate: '2026-06-15T09:00:00Z',
        pageUrl: urls.supportTickets(),
        testOptions: { viewport: { width: 1300, height: 800 } },
    },
    decorators: [
        mswDecorator({
            get: {
                '/api/environments/:team_id/': { ...MOCK_DEFAULT_TEAM, conversations_enabled: true },
                '/api/projects/:team_id/conversations/tickets/': toPaginatedResponse(MOCK_TICKETS),
                '/api/projects/:team_id/conversations/views/': toPaginatedResponse(MOCK_VIEWS),
            },
        }),
    ],
}
export default meta

type Story = StoryObj<{}>

export const TicketList: Story = {}

export const TicketListWithFilters: Story = {
    parameters: {
        pageUrl: `${urls.supportTickets()}?status=%5B%22open%22%2C%22pending%22%5D&priority=%5B%22high%22%5D`,
    },
}

// About 520px of scene: the favorite views collapse into one dropdown and the filter row wraps.
export const TicketListNarrow: Story = {
    parameters: {
        testOptions: { viewport: { width: 560, height: 800 } },
    },
}
