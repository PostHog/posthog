import { cleanup, fireEvent, render, screen } from '@testing-library/react'
import posthog from 'posthog-js'

import { initKeaTests } from '~/test/init'

import { FreeHistoricalSyncsBanner } from './FreeHistoricalSyncsBanner'

describe('FreeHistoricalSyncsBanner', () => {
    beforeEach(() => initKeaTests())
    afterEach(() => {
        cleanup()
        jest.restoreAllMocks()
    })

    it.each([
        { name: 'click', type: 'click', options: { button: 0 }, expectedCalls: 1 },
        { name: 'Ctrl-click', type: 'click', options: { ctrlKey: true }, expectedCalls: 1 },
        { name: 'Cmd-click', type: 'click', options: { metaKey: true }, expectedCalls: 1 },
        { name: 'middle-click', type: 'auxclick', options: { button: 1 }, expectedCalls: 1 },
        { name: 'right-click', type: 'auxclick', options: { button: 2 }, expectedCalls: 0 },
    ])('records pricing link activation on $name', ({ type, options, expectedCalls }) => {
        const capture = jest.spyOn(posthog, 'capture').mockImplementation()
        render(<FreeHistoricalSyncsBanner hideGetStarted />)
        fireEvent.click(screen.getByText('Learn more'))

        const link = screen.getByTestId('historical-sync-banner-pricing-link')
        fireEvent(link, new MouseEvent(type, { bubbles: true, ...options }))

        const pricingVisits = capture.mock.calls.filter(
            ([event]) => event === 'historical_sync_banner_pricing_link_clicked'
        )
        expect(pricingVisits).toHaveLength(expectedCalls)
    })
})
