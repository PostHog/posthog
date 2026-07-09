import '@testing-library/jest-dom'

import { act, cleanup, render } from '@testing-library/react'

import { TZLabel } from './index'

describe('TZLabel', () => {
    beforeEach(() => {
        jest.useFakeTimers()
        jest.setSystemTime(new Date('2026-03-16T10:11:15Z'))
        Object.defineProperty(document, 'hidden', { writable: true, value: false })
    })

    afterEach(() => {
        jest.clearAllTimers()
        jest.useRealTimers()
    })

    it('renders a full datetime when timestampStyle is absolute without custom formats', () => {
        const { container } = render(
            <TZLabel time="2026-03-16T10:11:12Z" timestampStyle="absolute" displayTimezone="UTC" showPopover={false} />
        )

        expect(container).toHaveTextContent(/March\s+16,\s+2026\s+10:11:12\s+AM/)
    })

    it('renders a full datetime when displayTimezone is set without custom formats', () => {
        const { container } = render(<TZLabel time="2026-03-16T10:11:12Z" displayTimezone="UTC" showPopover={false} />)

        expect(container).toHaveTextContent(/March\s+16,\s+2026\s+10:11:12\s+AM/)
    })

    describe('shared ticker', () => {
        // Relative labels used to run one 1s setInterval per instance — hundreds of timer
        // wake-ups per second in a table. These lock in the single shared interval and that
        // sharing didn't break the ticking or unmount cleanup.
        beforeEach(() => {
            // Unmount labels leaked by earlier tests so the shared ticker singleton starts idle
            // under this test's fake clock.
            cleanup()
        })
        it('mounted labels share a single interval and text still advances', () => {
            const first = render(<TZLabel time="2026-03-16T10:11:12Z" showPopover={false} />)
            const second = render(<TZLabel time="2026-03-16T10:10:15Z" showPopover={false} />)

            expect(jest.getTimerCount()).toBe(1)
            expect(second.container).toHaveTextContent('a minute ago')

            act(() => {
                jest.advanceTimersByTime(65_000)
            })

            expect(second.container).toHaveTextContent('2 minutes ago')

            first.unmount()
            second.unmount()
            expect(jest.getTimerCount()).toBe(0)
        })

        it('keeps ticking for a label mounted after all previous labels unmounted', () => {
            render(<TZLabel time="2026-03-16T10:11:12Z" showPopover={false} />).unmount()

            const remounted = render(<TZLabel time="2026-03-16T10:10:15Z" showPopover={false} />)
            act(() => {
                jest.advanceTimersByTime(65_000)
            })

            expect(remounted.container).toHaveTextContent('2 minutes ago')
        })
    })
})
