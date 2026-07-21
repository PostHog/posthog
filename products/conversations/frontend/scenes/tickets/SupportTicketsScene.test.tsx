import '@testing-library/jest-dom'

import { act, cleanup, render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { Provider } from 'kea'

import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'

import { Ticket } from '../../types'
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

describe('SupportTicketsTable bulk selection', () => {
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

    // Guards the LemonTable `bulkSelection` wiring: selecting a row must surface our
    // `renderActions` bulk-action bar. The selection mechanics themselves live in
    // useBulkSelection and are covered by useBulkSelection.test.ts.
    it('surfaces the "Update tickets" action once a ticket is selected', async () => {
        render(
            <Provider>
                <SupportTicketsTable />
            </Provider>
        )

        expect(screen.queryByText('Update tickets')).not.toBeInTheDocument()

        await userEvent.click(getRowCheckbox())

        expect(await screen.findByText('Update tickets')).toBeInTheDocument()
        expect(getRowCheckbox()).toBeChecked()
    })
})
