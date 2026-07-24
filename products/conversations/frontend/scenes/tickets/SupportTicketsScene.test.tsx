import '@testing-library/jest-dom'

import { act, cleanup, render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { Provider } from 'kea'
import { router } from 'kea-router'

import { urls } from 'scenes/urls'

import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'

import { Ticket } from '../../types'
import { ticketListBackTo } from '../ticket/SupportTicketScene'
import { SupportTicketsTable, SupportTicketsTableFilters } from './SupportTicketsScene'
import { supportTicketsSceneLogic } from './supportTicketsSceneLogic'

function makeTicket(overrides: Partial<Ticket> & Pick<Ticket, 'id' | 'ticket_number'>): Ticket {
    return {
        distinct_id: 'distinct-1',
        status: 'open',
        channel_source: 'email',
        anonymous_traits: {},
        identity_verified: false,
        ai_resolved: false,
        created_at: '2026-06-12T00:00:00Z',
        updated_at: '2026-06-12T00:00:00Z',
        message_count: 1,
        last_message_at: '2026-06-12T00:00:00Z',
        last_message_text: 'Hello',
        unread_team_count: 0,
        unread_customer_count: 0,
        ...overrides,
    }
}

const TICKETS = [
    makeTicket({ id: 'ticket-1', ticket_number: 1 }),
    makeTicket({ id: 'ticket-2', ticket_number: 2 }),
    makeTicket({ id: 'ticket-3', ticket_number: 3 }),
]

describe('SupportTicketsTable selection', () => {
    let logic: ReturnType<typeof supportTicketsSceneLogic.build>

    beforeEach(() => {
        useMocks({
            get: {
                '/api/projects/:team_id/conversations/tickets/': () => [
                    200,
                    { results: TICKETS, count: TICKETS.length },
                ],
                '/api/organizations/:organization_id/members/': () => [200, { results: [] }],
            },
        })
        initKeaTests()
        logic = supportTicketsSceneLogic()
        logic.mount()
        // Seed tickets directly so we don't depend on the debounced loadTickets request.
        act(() => {
            logic.actions.setTickets(TICKETS)
        })
    })

    afterEach(() => {
        logic.unmount()
        cleanup()
    })

    // Guards the checkbox-column wiring: a row checkbox toggles that ticket in the logic's selection.
    it('selects a ticket when its row checkbox is clicked', async () => {
        render(
            <Provider>
                <SupportTicketsTable />
            </Provider>
        )

        // Checkbox [0] is the header "select all on page"; [1] is the first row.
        const rowCheckbox = screen.getAllByRole('checkbox')[1]
        await userEvent.click(rowCheckbox)

        expect(logic.values.selectedTicketIds).toEqual(['ticket-1'])
    })

    // Select-all toggles every ticket on the page on, then off on a second click.
    it('toggles all page tickets via select-all', () => {
        const pageIds = TICKETS.map((t) => t.id)

        logic.actions.toggleSelectAllOnPage(pageIds)
        expect(logic.values.selectedTicketIds).toEqual(pageIds)

        logic.actions.toggleSelectAllOnPage(pageIds)
        expect(logic.values.selectedTicketIds).toEqual([])
    })

    // Tag state powers the tri-state editor: fully-applied vs partially-applied across the selection.
    it('marks a tag "all" when every selected ticket has it and "some" otherwise', () => {
        logic.actions.setTickets([
            makeTicket({ id: 'ticket-1', ticket_number: 1, tags: ['billing', 'urgent'] }),
            makeTicket({ id: 'ticket-2', ticket_number: 2, tags: ['billing'] }),
        ])
        logic.actions.setSelectedTicketIds(['ticket-1', 'ticket-2'])

        expect(logic.values.selectedTicketTagStates).toEqual([
            { tag: 'billing', state: 'all' },
            { tag: 'urgent', state: 'some' },
        ])
    })

    // Optimistic patch keeps the selection (and the tag editor) open across edits.
    it('patches tags on selected tickets without dropping the selection or touching others', () => {
        logic.actions.setTickets([
            makeTicket({ id: 'ticket-1', ticket_number: 1, tags: ['old'] }),
            makeTicket({ id: 'ticket-2', ticket_number: 2, tags: ['old'] }),
            makeTicket({ id: 'ticket-3', ticket_number: 3, tags: ['keep'] }),
        ])
        logic.actions.setSelectedTicketIds(['ticket-1', 'ticket-2'])

        logic.actions.applyTicketTagPatch(['ticket-1', 'ticket-2'], ['new'], ['old'])

        const tagsById = Object.fromEntries(logic.values.tickets.map((t) => [t.id, t.tags]))
        expect(tagsById['ticket-1']).toEqual(['new'])
        expect(tagsById['ticket-2']).toEqual(['new'])
        expect(tagsById['ticket-3']).toEqual(['keep'])
        expect(logic.values.selectedTicketIds).toEqual(['ticket-1', 'ticket-2'])
    })

    // Regression: opening a ticket from a filtered list dropped the filters, so the ticket's
    // back arrow returned to the unfiltered "all tickets" list instead of the view the user
    // was on. The row now carries the list's query string onto the ticket URL so the back
    // arrow can restore it.
    it('carries the active filters onto the ticket URL when a row is opened', async () => {
        act(() => {
            logic.actions.setStatusFilter(['open'])
        })
        // The filter is reflected in the list URL first.
        await waitFor(() => expect(router.values.searchParams.status).not.toBeUndefined())

        render(
            <Provider>
                <SupportTicketsTable />
            </Provider>
        )

        // Click the ticket row itself (not the selection checkbox). The router pathname is
        // project-scoped (e.g. /project/997/...), so match on the ticket path suffix.
        const rows = screen.getAllByRole('row')
        await userEvent.click(rows[rows.length - 1])

        await waitFor(() =>
            expect(router.values.location.pathname).toContain(
                urls.supportTicketDetail(TICKETS[TICKETS.length - 1].ticket_number)
            )
        )
        // Filters ride along on the ticket URL so the back arrow returns to this view.
        expect(router.values.searchParams.status).not.toBeUndefined()
    })

    // Regression (the back half): the ticket's back arrow rebuilds the list URL from the
    // filters carried in the ticket page's query string via `ticketListBackTo`. If that
    // construction drops the filters, the arrow lands on the unfiltered "all tickets" list
    // — the actual bug. This follows the round trip: open a filtered ticket, then the back
    // arrow, and confirm it lands back on the filtered list.
    it('sends the ticket back arrow to the filtered list', async () => {
        act(() => {
            logic.actions.setStatusFilter(['open'])
        })
        await waitFor(() => expect(router.values.searchParams.status).not.toBeUndefined())

        render(
            <Provider>
                <SupportTicketsTable />
            </Provider>
        )

        // Open the ticket from the filtered list; the row carries the filters onto its URL.
        // (Router pathnames are project-scoped, so match on the path suffix.)
        const rows = screen.getAllByRole('row')
        await userEvent.click(rows[rows.length - 1])
        await waitFor(() =>
            expect(router.values.location.pathname).toContain(
                urls.supportTicketDetail(TICKETS[TICKETS.length - 1].ticket_number)
            )
        )

        // The back arrow's target is built from the ticket page's live query string. It must
        // point back at the ticket list and keep the status filter.
        const backPath = ticketListBackTo(router.values.searchParams).path ?? ''
        expect(backPath.split('?')[0]).toBe(urls.supportTickets())
        expect(backPath).toContain('status')

        // Follow the back arrow: it lands on the filtered ticket list, not the unfiltered
        // "all tickets" view.
        act(() => {
            router.actions.push(backPath)
        })
        await waitFor(() => expect(router.values.location.pathname).toContain(urls.supportTickets()))
        expect(router.values.searchParams.status).not.toBeUndefined()
    })
})

describe('SupportTicketsTableFilters count', () => {
    let logic: ReturnType<typeof supportTicketsSceneLogic.build>
    let mockCount = 0

    beforeEach(() => {
        mockCount = 0
        useMocks({
            get: {
                '/api/projects/:team_id/conversations/tickets/': () => [
                    200,
                    { results: [TICKETS[0]], count: mockCount },
                ],
                '/api/organizations/:organization_id/members/': () => [200, { results: [] }],
                '/api/projects/:team_id/tags': () => [200, []],
            },
        })
        initKeaTests()
        logic = supportTicketsSceneLogic()
        logic.mount()
    })

    afterEach(() => {
        logic.unmount()
        cleanup()
    })

    // Set the count directly so the assertion doesn't race the debounced loadTickets; keep the
    // mock in sync so a background reload can't reset the value out from under the assertion.
    function setCount(count: number): void {
        mockCount = count
        act(() => {
            logic.actions.setTotalCount(count)
        })
    }

    it.each([
        ['pluralizes the count of tickets matching the current query', 42, '42 tickets'],
        ['uses the singular noun for a single ticket', 1, '1 ticket'],
    ])('%s', async (_name, count, expected) => {
        setCount(count)

        render(
            <Provider>
                <SupportTicketsTableFilters />
            </Provider>
        )

        expect(await screen.findByText(expected)).toBeInTheDocument()
    })
})
