import { render, screen } from '@testing-library/react'

import { TicketEmailDelivery } from './TicketEmailDelivery'

describe('TicketEmailDelivery', () => {
    it.each([
        ['off', { email_delivery: null, email_from: 'person@example.com' }, null, false],
        [
            'pending',
            { email_delivery: 'pending' as const, email_from: 'person@example.com' },
            'Waiting for confirmation',
            false,
        ],
        ['active', { email_delivery: 'active' as const, email_from: 'person@example.com' }, 'person@example.com', true],
    ])('shows the %s state', (_name, ticket, expectedText, expectsConfirmedBadge) => {
        const { container } = render(<TicketEmailDelivery ticket={ticket} />)

        expect(container.textContent).toBe(expectedText ? `Email delivery${expectedText}` : '')
        expect(screen.queryByLabelText('Email confirmed') !== null).toBe(expectsConfirmedBadge)
    })
})
