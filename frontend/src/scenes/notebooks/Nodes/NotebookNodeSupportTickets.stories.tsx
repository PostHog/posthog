import { Meta, StoryObj } from '@storybook/react'
import { BindLogic } from 'kea'
import { useMemo } from 'react'

import { CountedPaginatedResponse } from 'lib/api'
import { FEATURE_FLAGS } from 'lib/constants'
import { App } from 'scenes/App'
import { urls } from 'scenes/urls'

import { mswDecorator, useStorybookMocks } from '~/mocks/browser'
import { CustomerProfileScope } from '~/types'

import type { Ticket } from 'products/conversations/frontend/types'
import { customerProfileLogic } from 'products/customer_analytics/frontend/customerProfileLogic'

import { notebookTestTemplate } from '../Notebook/__mocks__/notebook-template-for-snapshot'
import { NotebookType } from '../types'

const PERSON_ID = '01234567-89ab-cdef-0123-456789abcdef'
const DISTINCT_IDS = ['user@example.com']

function makeNotebook(shortId: string): NotebookType {
    return {
        ...notebookTestTemplate('Support Tickets Test', [
            {
                type: 'ph-support-tickets',
                attrs: {
                    personId: PERSON_ID,
                    distinctIds: DISTINCT_IDS,
                    nodeId: 'st-node-1',
                    title: 'Support tickets',
                },
            },
        ]),
        short_id: shortId,
    }
}

function makeTicket(overrides: Partial<Ticket> & { id: string; ticket_number: number }): Ticket {
    return {
        distinct_id: 'user@example.com',
        status: 'open',
        channel_source: 'widget',
        anonymous_traits: {},
        ai_resolved: false,
        created_at: '2024-01-10T14:30:00Z',
        updated_at: '2024-01-11T09:15:00Z',
        message_count: 3,
        last_message_at: '2024-01-11T09:15:00Z',
        last_message_text: 'Thanks for reaching out, we are looking into this.',
        unread_team_count: 0,
        unread_customer_count: 0,
        ...overrides,
    }
}

const ticketsResponse = (tickets: Ticket[]): CountedPaginatedResponse<Ticket> => ({
    count: tickets.length,
    next: null,
    previous: null,
    results: tickets,
})

const notebooksListMock = {
    count: 1,
    next: null,
    previous: null,
    results: [
        {
            id: 'notebook-st',
            short_id: 'st-with-tickets',
            title: 'Support Tickets Test',
            created_at: '2024-01-01T00:00:00Z',
            last_modified_at: '2024-01-01T00:00:00Z',
        },
    ],
}

const CANVAS_SHORT_ID = `canvas-${PERSON_ID}`

function AppWithProfileContext(): JSX.Element {
    const attrs = useMemo(() => ({ personId: PERSON_ID, distinctIds: DISTINCT_IDS }), [])
    const profileProps = {
        attrs,
        scope: CustomerProfileScope.PERSON,
        key: `person-${PERSON_ID}`,
        canvasShortId: CANVAS_SHORT_ID,
    }
    return (
        <BindLogic logic={customerProfileLogic} props={profileProps}>
            <App />
        </BindLogic>
    )
}

const sampleTickets: Ticket[] = [
    makeTicket({
        id: 'ticket-1',
        ticket_number: 1001,
        status: 'new',
        priority: 'high',
        channel_source: 'widget',
        last_message_text: 'I cannot log in to my account after the latest update.',
        unread_team_count: 2,
        person: {
            id: 'p1',
            name: 'Alice Smith',
            distinct_ids: DISTINCT_IDS,
            properties: { email: 'alice@example.com' },
        },
    }),
    makeTicket({
        id: 'ticket-2',
        ticket_number: 1002,
        status: 'open',
        priority: 'medium',
        channel_source: 'email',
        last_message_text: 'The dashboard charts are not loading properly.',
        unread_team_count: 0,
        person: {
            id: 'p1',
            name: 'Alice Smith',
            distinct_ids: DISTINCT_IDS,
            properties: { email: 'alice@example.com' },
        },
    }),
    makeTicket({
        id: 'ticket-3',
        ticket_number: 1003,
        status: 'resolved',
        channel_source: 'slack',
        last_message_text: 'Thanks, that fixed it!',
        unread_team_count: 0,
        person: {
            id: 'p1',
            name: 'Alice Smith',
            distinct_ids: DISTINCT_IDS,
            properties: { email: 'alice@example.com' },
        },
    }),
]

const meta: Meta = {
    component: App,
    title: 'Scenes-App/Notebooks/Nodes/Support Tickets',
    parameters: {
        layout: 'fullscreen',
        viewMode: 'story',
        mockDate: '2024-01-15',
        featureFlags: [FEATURE_FLAGS.PRODUCT_SUPPORT],
    },
    decorators: [
        mswDecorator({
            get: {
                'api/environments/:team_id/customer_profile_configs/': { count: 0, results: [] },
                'api/projects/:team_id/notebooks/': notebooksListMock,
                'api/projects/:team_id/notebooks/st-with-tickets/': makeNotebook('st-with-tickets'),
                'api/projects/:team_id/notebooks/st-empty/': makeNotebook('st-empty'),
            },
        }),
    ],
}
export default meta

type Story = StoryObj<{}>

export const WithTickets: Story = {
    render: () => {
        useStorybookMocks({
            get: {
                'api/projects/:team_id/conversations/tickets/': ticketsResponse(sampleTickets),
            },
        })
        return <AppWithProfileContext />
    },
    parameters: {
        pageUrl: urls.notebook('st-with-tickets'),
        testOptions: { waitForSelector: '.LemonTable' },
    },
}

export const Empty: Story = {
    render: () => {
        useStorybookMocks({
            get: {
                'api/projects/:team_id/conversations/tickets/': ticketsResponse([]),
            },
        })
        return <AppWithProfileContext />
    },
    parameters: {
        pageUrl: urls.notebook('st-empty'),
        testOptions: { waitForSelector: '.LemonTable' },
    },
}
