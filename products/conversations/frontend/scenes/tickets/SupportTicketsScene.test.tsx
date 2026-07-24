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
import { SupportTicketsTable } from './SupportTicketsScene'
import { supportTicketsSceneLogic } from './supportTicketsSceneLogic'

const TICKET: Ticket = {
    id: 'ticket-1',
    ticket_number: 1,
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
}

describe('SupportTicketsTable selection', () => {
    let logic: ReturnType<typeof supportTicketsSceneLogic.build>

    beforeEach(() => {
        useMocks({
            get: {
                '/api/projects/:team_id/conversations/tickets/': () => [200, { results: [TICKET], count: 1 }],
                '/api/organizations/:organization_id/members/': () => [200, { results: [] }],
            },
        })
        initKeaTests()
        logic = supportTicketsSceneLogic()
        logic.mount()
        // Seed a ticket directly so we don't depend on the debounced loadTickets request.
        act(() => {
            logic.actions.setTickets([TICKET])
        })
    })

    afterEach(() => {
        logic.unmount()
        cleanup()
    })

    function getRowCheckbox(): HTMLInputElement {
        // Two checkboxes render: [0] the header "select all on page", [1] the single row.
        const checkboxes = screen.getAllByRole('checkbox')
        expect(checkboxes).toHaveLength(2)
        return checkboxes[1] as HTMLInputElement
    }

    // Regression: the hook selection (selectedKeys) and kea (selectedTicketIds) were synced by
    // two effects, and on the first click the "clear when kea is empty" effect fired before the
    // push effect had propagated — instantly wiping the selection. The checkbox never stuck.
    it('keeps a row checked after clicking and pushes the id into kea', async () => {
        render(
            <Provider>
                <SupportTicketsTable />
            </Provider>
        )

        const rowCheckbox = getRowCheckbox()
        expect(rowCheckbox).not.toBeChecked()

        await userEvent.click(rowCheckbox)

        await waitFor(() => expect(getRowCheckbox()).toBeChecked())
        expect(logic.values.selectedTicketIds).toEqual([TICKET.id])
    })

    it('clears the checkbox when the kea selection is reset externally', async () => {
        render(
            <Provider>
                <SupportTicketsTable />
            </Provider>
        )

        await userEvent.click(getRowCheckbox())
        await waitFor(() => expect(getRowCheckbox()).toBeChecked())

        // A bulk update / page reload resets the kea selection — the hook should follow.
        act(() => {
            logic.actions.clearSelectedTickets()
        })

        await waitFor(() => expect(getRowCheckbox()).not.toBeChecked())
        expect(logic.values.selectedTicketIds).toEqual([])
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
            expect(router.values.location.pathname).toContain(urls.supportTicketDetail(TICKET.ticket_number))
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
            expect(router.values.location.pathname).toContain(urls.supportTicketDetail(TICKET.ticket_number))
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
