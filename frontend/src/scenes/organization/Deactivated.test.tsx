import { MOCK_DEFAULT_ORGANIZATION, MOCK_DEFAULT_PROJECT, MOCK_DEFAULT_TEAM } from 'lib/api.mock'

import '@testing-library/jest-dom'

import { cleanup, render, screen, waitFor } from '@testing-library/react'

import { urls } from 'scenes/urls'

import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'
import { OrganizationType } from '~/types'

import { OrganizationDeactivated } from './Deactivated'
import { UNPAID_INVOICE_REASON } from './organizationDeactivatedLogic'

const INVOICE_LINK = 'https://invoice.stripe.com/i/acct_test/inv_test'

describe('OrganizationDeactivated', () => {
    let requestedStatuses: (string | null)[]
    let invoices: { count: number; link: string | null }

    beforeEach(() => {
        requestedStatuses = []
        useMocks({
            get: {
                '/api/billing/get_invoices': ({ request }) => {
                    requestedStatuses.push(new URL(request.url).searchParams.get('status'))
                    return [200, invoices]
                },
            },
        })
    })

    const renderWith = (reason: string, unpaidInvoices: { count: number; link: string | null }): void => {
        invoices = unpaidInvoices
        initKeaTests(true, MOCK_DEFAULT_TEAM, MOCK_DEFAULT_PROJECT, {
            ...MOCK_DEFAULT_ORGANIZATION,
            is_active: false,
            is_not_active_reason: reason,
        } as OrganizationType)
        render(<OrganizationDeactivated />)
    }

    afterEach(cleanup)

    it('links straight to the unpaid invoice when billing paused access for it', async () => {
        renderWith(UNPAID_INVOICE_REASON, { count: 1, link: INVOICE_LINK })

        await waitFor(() => expect(screen.getByText('Pay invoice').closest('a')).toHaveAttribute('href', INVOICE_LINK))
        expect(requestedStatuses).toEqual(['uncollectible'])
        expect(screen.getByText('Go to billing').closest('a')).toHaveAttribute('href', urls.organizationBilling())
    })

    it('falls back to billing when no unpaid invoice comes back', async () => {
        renderWith(UNPAID_INVOICE_REASON, { count: 0, link: null })

        await waitFor(() => expect(requestedStatuses).toEqual(['uncollectible']))
        expect(screen.queryByText('Pay invoice')).not.toBeInTheDocument()
        expect(screen.getByText('Go to billing').closest('a')).toHaveAttribute('href', urls.organizationBilling())
    })

    it('offers no payment for a deactivation billing did not make', async () => {
        renderWith('Access revoked due to unpaid balance.', { count: 1, link: INVOICE_LINK })

        expect(await screen.findByText(/Access revoked due to unpaid balance/)).toBeInTheDocument()
        expect(screen.queryByText('Pay invoice')).not.toBeInTheDocument()
        expect(screen.queryByText('Go to billing')).not.toBeInTheDocument()
    })
})
