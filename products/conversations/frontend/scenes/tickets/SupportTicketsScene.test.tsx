import '@testing-library/jest-dom'

import { act, cleanup, render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { Provider } from 'kea'

import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'

import { Ticket } from '../../types'
import { SupportTicketsTable, SupportTicketsTableFilters } from './SupportTicketsScene'
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
})

describe('SupportTicketsTableFilters count', () => {
    let logic: ReturnType<typeof supportTicketsSceneLogic.build>
    let mockCount = 0

    beforeEach(() => {
        mockCount = 0
        useMocks({
            get: {
                '/api/projects/:team_id/conversations/tickets/': () => [200, { results: [TICKET], count: mockCount }],
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
