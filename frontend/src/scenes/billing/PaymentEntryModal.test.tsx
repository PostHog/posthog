import '@testing-library/jest-dom'

import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { Provider } from 'kea'

import { organizationLogic } from 'scenes/organizationLogic'

import { initKeaTests } from '~/test/init'

import { paymentEntryLogic } from './paymentEntryLogic'
import { PaymentForm } from './PaymentEntryModal'

const mockConfirmPayment = jest.fn((_: { confirmParams: { return_url: string } }) => new Promise(() => {}))

jest.mock('@stripe/react-stripe-js', () => ({
    PaymentElement: () => null,
    useStripe: () => ({ confirmPayment: mockConfirmPayment }),
    useElements: () => ({}),
}))

describe('PaymentForm', () => {
    beforeEach(() => {
        initKeaTests()
        paymentEntryLogic.mount()
    })

    afterEach(() => {
        cleanup()
        paymentEntryLogic.unmount()
    })

    it('returns from Stripe to the paying organization', async () => {
        const organizationId = organizationLogic.values.currentOrganization!.id
        paymentEntryLogic.actions.beginPaymentFlow(organizationId, '/project/1/replay')
        render(
            <Provider>
                <PaymentForm />
            </Provider>
        )
        fireEvent.click(screen.getByText('Submit'))
        await waitFor(() => expect(mockConfirmPayment).toHaveBeenCalledTimes(1))
        const returnUrl = new URL(mockConfirmPayment.mock.calls[0][0].confirmParams.return_url)
        expect(returnUrl.pathname).toBe('/billing/authorization_status')
        expect(returnUrl.searchParams.get('organization_id')).toBe(organizationId)
        expect(returnUrl.searchParams.get('postRedirectPath')).toBe('/project/1/replay')
    })
})
