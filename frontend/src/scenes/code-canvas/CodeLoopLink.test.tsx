import { cleanup, render } from '@testing-library/react'

import { CodeLoopLink, loopDeepLink } from './CodeLoopLink'

describe('CodeLoopLink', () => {
    beforeEach(() => {
        // jsdom refuses a real navigation, so stand in a location whose href we can read back.
        Object.defineProperty(window, 'location', {
            configurable: true,
            value: { ...window.location, href: '' },
        })
    })

    afterEach(() => {
        cleanup()
    })

    it('encodes the loop id into the desktop deep link', () => {
        expect(loopDeepLink('loop/1')).toBe('posthog-code://loop/loop%2F1')
    })

    it('sends the browser to the desktop app for the rendered loop', () => {
        render(<CodeLoopLink loopId="loop-1" />)

        expect(window.location.href).toBe('posthog-code://loop/loop-1')
    })
})
