/* oxlint-disable react-hooks/rules-of-hooks -- useMocks is a test helper, not a React hook */
import '@testing-library/jest-dom'

import { cleanup, render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { Provider } from 'kea'

import { supportLogic } from 'lib/components/Support/supportLogic'
import { paymentEntryLogic } from 'scenes/billing/paymentEntryLogic'

import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'

import { PaymentEntryModal } from './PaymentEntryModal'

const BLOCKED_MESSAGE = "You've been blocked from subscribing. Please contact support."

describe('PaymentEntryModal', () => {
    beforeEach(() => {
        useMocks({
            post: {
                'api/billing/activate/authorize': () => [403, { detail: BLOCKED_MESSAGE }],
            },
        })
        initKeaTests()
        paymentEntryLogic.mount()
        supportLogic.mount()
    })

    afterEach(cleanup)

    it('files a blocked upgrade as a billing issue, which every plan may raise', async () => {
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
})
