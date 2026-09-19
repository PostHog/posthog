import '@testing-library/jest-dom'

import { cleanup, render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { useActions, useValues } from 'kea'

import { BillingFeatureType, BillingProductV2Type } from '~/types'

import { PlanCards, formatDataRetentionFeature } from './PlanCards'

jest.mock('kea', () => ({
    ...jest.requireActual('kea'),
    useValues: jest.fn(),
    useActions: jest.fn(),
}))

describe('PlanCards', () => {
    describe('formatDataRetentionFeature', () => {
        const makeFeature = (limit?: number | null, unit?: string | null): BillingFeatureType =>
            ({ key: 'session_replay_data_retention', name: 'Data retention', limit, unit }) as BillingFeatureType

        // pluralize() joins the count and unit with a non-breaking space (U+00A0); normalize it for readable assertions.
        const normalize = (value: string | null): string | null =>
            value ? value.split(String.fromCharCode(160)).join(' ') : null

        it.each([
            // Analytics retention is supplied in years; session replay in months. Both must read naturally.
            [7, 'years', '7 years data retention'],
            [1, 'year', '1 year data retention'],
            [3, 'months', '3 months data retention'],
            [1, 'month', '1 month data retention'],
            [90, 'days', '90 days data retention'],
        ])('formats limit %s with unit "%s" as "%s"', (limit, unit, expected) => {
            expect(normalize(formatDataRetentionFeature(makeFeature(limit, unit)))).toBe(expected)
        })

        it.each([
            ['feature is undefined', undefined],
            ['limit is missing', makeFeature(undefined, 'years')],
            ['unit is missing', makeFeature(7, undefined)],
        ])('returns null when %s', (_, feature) => {
            expect(formatDataRetentionFeature(feature as BillingFeatureType | undefined)).toBe(null)
        })
    })

    describe('plan selection', () => {
        const startPaymentEntryFlow = jest.fn()
        const goToNextStep = jest.fn()

        const renderCards = (): void => {
            ;(useValues as jest.Mock).mockReturnValue({
                billing: null,
                featureFlags: {},
                billingProductLoading: null,
            })
            ;(useActions as jest.Mock).mockReturnValue({
                startPaymentEntryFlow,
                goToNextStep,
                reportOnboardingStepCompleted: jest.fn(),
                reportBillingCTAShown: jest.fn(),
            })
            render(<PlanCards product={{ type: 'product_analytics', plans: [] } as unknown as BillingProductV2Type} />)
        }

        beforeEach(() => {
            jest.clearAllMocks()
        })

        afterEach(cleanup)

        // Reading the paid card used to start the payment flow, because its whole body carried the
        // click handler.
        it.each(['Unlimited usage', 'Starts at'])(
            'does not start the payment flow when "%s" in the paid card is clicked',
            async (text) => {
                renderCards()

                await userEvent.click(screen.getByText(text))

                expect(startPaymentEntryFlow).not.toHaveBeenCalled()
            }
        )

        it('starts the payment flow from the paid card button', async () => {
            renderCards()

            await userEvent.click(screen.getByText('Unlock all features'))

            expect(startPaymentEntryFlow).toHaveBeenCalledTimes(1)
        })

        it('advances the step when the free card body is clicked', async () => {
            renderCards()

            await userEvent.click(screen.getByText('Community support'))

            expect(goToNextStep).toHaveBeenCalledTimes(1)
            expect(startPaymentEntryFlow).not.toHaveBeenCalled()
        })
    })
})
