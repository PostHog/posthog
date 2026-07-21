import '@testing-library/jest-dom'

import { act, cleanup, render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { Provider } from 'kea'

import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'

import { Ticket } from '../../types'
import { SupportTicketsTable } from './SupportTicketsScene'
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
})
