/* oxlint-disable react-hooks/rules-of-hooks -- useMocks is a test helper, not a React hook */
import '@testing-library/jest-dom'

import { act, cleanup, render, screen } from '@testing-library/react'
import { Provider } from 'kea'

import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'

import { Billing } from './Billing'

describe('Billing', () => {
    beforeEach(() => {
        initKeaTests()
    })

    afterEach(async () => {
        cleanup()
        await act(async () => {
            await new Promise((r) => setTimeout(r, 0))
        })
    })

    // The coupon request runs beside the billing overview and hits the same billing service, so a
    // slow service leaves it open. The page must still offer the retry instead of a spinner.
    it('offers the retry while the coupon request is still open', async () => {
        let releaseCoupons = (): void => {}
        const couponsAnswered = new Promise<void>((resolve) => {
            releaseCoupons = resolve
        })
        useMocks({
            get: {
                '/api/billing': () => [
                    503,
                    {
                        type: 'server_error',
                        code: 'billing_service_unavailable',
                        detail: 'Billing is taking longer than usual to answer. Try again in a moment.',
                    },
                ],
                '/api/billing/coupons/overview': async () => {
                    await couponsAnswered
                    return [200, { claimed_coupons: [] }]
                },
            },
        })

        render(
            <Provider>
                <Billing />
            </Provider>
        )

        expect(
            await screen.findByText('Billing is taking longer than usual to answer. Try again in a moment.')
        ).toBeInTheDocument()
        // LemonBanner renders its action once per layout, so the count is not the point here.
        expect(screen.getAllByText('Try again')).not.toHaveLength(0)

        releaseCoupons()
    })
})
