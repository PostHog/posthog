/* oxlint-disable react-hooks/rules-of-hooks -- useMocks is a test helper, not a React hook */
import '@testing-library/jest-dom'

import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { Provider } from 'kea'

import { supportLogic } from 'lib/components/Support/supportLogic'
import { FEATURE_FLAGS } from 'lib/constants'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { organizationLogic } from 'scenes/organizationLogic'

import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'

import { paymentEntryLogic } from './paymentEntryLogic'
import { PaymentEntryModal, PaymentForm } from './PaymentEntryModal'

const mockConfirmPayment = jest.fn((_: { confirmParams: { return_url: string } }) => new Promise(() => {}))
let mockStripeReady = true
let mockElementsReady = true

jest.mock('@stripe/react-stripe-js', () => ({
    PaymentElement: () => null,
    useStripe: () => (mockStripeReady ? { confirmPayment: mockConfirmPayment } : null),
    useElements: () => (mockElementsReady ? {} : null),
}))

const BLOCKED_MESSAGE = "You've been blocked from subscribing. Please contact support."

describe('PaymentForm', () => {
    beforeEach(() => {
        mockStripeReady = true
        mockElementsReady = true
        initKeaTests()
        paymentEntryLogic.mount()
    })

    afterEach(() => {
        cleanup()
        paymentEntryLogic.unmount()
    })

    it.each([
        { waitingFor: 'Stripe', stripeReady: false, elementsReady: true },
        { waitingFor: 'Elements', stripeReady: true, elementsReady: false },
        { waitingFor: 'Stripe and Elements', stripeReady: false, elementsReady: false },
    ])('waits for $waitingFor before confirming payment', async ({ stripeReady, elementsReady }) => {
        const organizationId = organizationLogic.values.currentOrganization!.id
        paymentEntryLogic.actions.beginPaymentFlow(organizationId, '/project/1/replay')
        mockStripeReady = stripeReady
        mockElementsReady = elementsReady
        const { rerender } = render(
            <Provider>
                <PaymentForm />
            </Provider>
        )
        expect(screen.getByText('Submit').closest('button')).toHaveAttribute('aria-disabled', 'true')
        fireEvent.click(screen.getByText('Submit'))
        expect(mockConfirmPayment).not.toHaveBeenCalled()
        expect(paymentEntryLogic.values.stripeError).toBeNull()

        mockStripeReady = true
        mockElementsReady = true
        rerender(
            <Provider>
                <PaymentForm />
            </Provider>
        )
        expect(screen.getByText('Submit').closest('button')).toHaveAttribute('aria-disabled', 'false')
        fireEvent.click(screen.getByText('Submit'))
        await waitFor(() => expect(mockConfirmPayment).toHaveBeenCalledTimes(1))
        const returnUrl = new URL(mockConfirmPayment.mock.calls[0][0].confirmParams.return_url)
        expect(returnUrl.pathname).toBe('/billing/authorization_status')
        expect(returnUrl.searchParams.get('organization_id')).toBe(organizationId)
        expect(returnUrl.searchParams.get('postRedirectPath')).toBe('/project/1/replay')
    })
})

describe('PaymentEntryModal', () => {
    beforeEach(() => {
        useMocks({
            post: {
                '/api/billing/activate/authorize': () => [403, { detail: BLOCKED_MESSAGE }],
            },
        })
        initKeaTests()
        paymentEntryLogic.mount()
        supportLogic.mount()
        paymentEntryLogic.actions.beginPaymentFlow(organizationLogic.values.currentOrganization!.id)
    })

    afterEach(cleanup)

    it('files a blocked upgrade as a billing issue, which every plan may raise', async () => {
        featureFlagLogic.actions.setFeatureFlags([], { [FEATURE_FLAGS.PAYMENT_ENTRY_CONTACT_SUPPORT]: true })
        render(
            <Provider>
                <PaymentEntryModal />
            </Provider>
        )
        paymentEntryLogic.actions.showPaymentEntryModal()

        const contactSupport = await screen.findByText('Contact support')
        await userEvent.click(contactSupport)

        await waitFor(() => expect(supportLogic.values.sendSupportRequest.billing_issue).toBe(true))
        expect(supportLogic.values.sendSupportRequest.message).toContain('Failed to initialize payment')
        expect(paymentEntryLogic.values.paymentEntryModalOpen).toBe(false)
    })

    it('hides contact support while the flag is off', async () => {
        featureFlagLogic.actions.setFeatureFlags([], {})
        render(
            <Provider>
                <PaymentEntryModal />
            </Provider>
        )
        paymentEntryLogic.actions.showPaymentEntryModal()

        await screen.findByText('Close')
        expect(document.querySelector('[data-attr="payment-entry-api-error-contact-support"]')).not.toBeInTheDocument()
    })
})
