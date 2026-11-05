import { cleanup, render } from '@testing-library/react'
import { router } from 'kea-router'

import { urls } from 'scenes/urls'

import { initKeaTests } from '~/test/init'

import { AIObservabilityHumanReviews } from './AIObservabilityHumanReviews'

jest.mock('../reviewQueues/AIObservabilityReviewQueues', () => ({ AIObservabilityReviewQueues: () => null }))
jest.mock('./AIObservabilityReviews', () => ({ AIObservabilityReviews: () => null }))

describe('AIObservabilityHumanReviews', () => {
    afterEach(cleanup)

    it.each(['llma-review-queues-tab', 'llma-trace-reviews-tab'])(
        'leaves the trace drawer params out of the %s link and keeps the filters',
        (tab) => {
            initKeaTests()
            router.actions.push(`${urls.aiObservabilityReviews()}?date_from=-7d&trace=a&ts=2026&step=x`)

            const { container } = render(<AIObservabilityHumanReviews />)

            const href = container.querySelector(`[data-attr="${tab}"]`)?.closest('a')?.getAttribute('href')
            expect(href).toContain('date_from=-7d')
            expect(href).not.toMatch(/trace=|ts=|step=/)
        }
    )
})
