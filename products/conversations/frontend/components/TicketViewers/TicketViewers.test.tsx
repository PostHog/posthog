import '@testing-library/jest-dom'

import { render } from '@testing-library/react'

import type { TicketViewer } from './ticketPresence'
import { TicketViewers } from './TicketViewers'

describe('TicketViewers', () => {
    const alice: TicketViewer = { id: 1, email: 'alice@example.com', first_name: 'Alice', last_name: 'Ames' }
    const bob: TicketViewer = { id: 2, email: 'bob@example.com', first_name: 'Bob', last_name: '' }

    it('renders nothing when no one else is viewing', () => {
        const { container } = render(<TicketViewers viewers={[]} />)
        expect(container).toBeEmptyDOMElement()
    })

    // Regression guard: without an accessible name the viewer names live only in the hover tooltip,
    // so screen-reader users cannot tell who is viewing. The row carries role="img" for that name.
    it('exposes the viewer names as the row accessible name, not only the hover tooltip', () => {
        const { container } = render(<TicketViewers viewers={[alice, bob]} also />)
        expect(container.querySelector('[role="img"]')).toHaveAccessibleName(
            'Alice Ames and Bob are also viewing this ticket'
        )
    })
})
