import { fireEvent, render } from '@testing-library/react'

import { ErrorNetwork } from './ErrorNetwork'

describe('ErrorNetwork', () => {
    // Regression guard: the reload button used to call a bare `window.location.reload()`, which
    // can be served the same cached document that referenced the now-missing chunk, sending the
    // user right back to this same page. Replacing to a cache-busted URL forces a fresh fetch.
    it('busts the cache instead of reloading in place', () => {
        const replace = jest.fn()
        const originalLocation = window.location
        Object.defineProperty(window, 'location', {
            configurable: true,
            writable: true,
            value: { ...originalLocation, href: 'https://app.posthog.com/insights', replace },
        })

        try {
            const { getByText } = render(<ErrorNetwork />)
            fireEvent.click(getByText('Refresh page'))

            expect(replace).toHaveBeenCalledTimes(1)
            const [calledUrl] = replace.mock.calls[0]
            expect(calledUrl).toMatch(/^https:\/\/app\.posthog\.com\/insights\?_reload=\d+$/)
        } finally {
            Object.defineProperty(window, 'location', {
                configurable: true,
                writable: true,
                value: originalLocation,
            })
        }
    })
})
