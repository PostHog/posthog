import '@testing-library/jest-dom'

import { render } from '@testing-library/react'

import { dayjs } from 'lib/dayjs'

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

    it('degrades to a plain timestamp instead of crashing when formatting throws', () => {
        // dayjs's stacked format plugins have overflowed the call stack in some browsers
        // ("too much recursion"). TZLabel renders all over the app, so a throwing format
        // call must degrade gracefully rather than take down the scene it sits in.
        const time = dayjs('2026-03-16T10:11:12Z')
        jest.spyOn(time, 'fromNow').mockImplementation(() => {
            throw new RangeError('too much recursion')
        })

        const { container } = render(<TZLabel time={time} showPopover={false} />)

        expect(container).toHaveTextContent('2026-03-16T10:11:12.000Z')
    })
})
