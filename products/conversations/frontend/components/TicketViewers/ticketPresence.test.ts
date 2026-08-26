import { type TicketViewer, ticketViewersTooltip } from './ticketPresence'

describe('ticketViewersTooltip', () => {
    const alice: TicketViewer = { id: 1, email: 'alice@example.com', first_name: 'Alice', last_name: 'Ames' }
    const bob: TicketViewer = { id: 2, email: 'bob@example.com', first_name: 'Bob' }
    const unnamed: TicketViewer = { id: 3, email: 'carol@example.com', first_name: '' }

    it.each([
        [[alice], false, 'Alice Ames is viewing this ticket'],
        [[alice], true, 'Alice Ames is also viewing this ticket'],
        [[alice, bob], true, 'Alice Ames and Bob are also viewing this ticket'],
        [[alice, bob, unnamed], false, 'Alice Ames, Bob, and carol@example.com are viewing this ticket'],
    ])('names %j (also: %s) as "%s"', (viewers, also, expected) => {
        expect(ticketViewersTooltip(viewers, { also })).toBe(expected)
    })
})
