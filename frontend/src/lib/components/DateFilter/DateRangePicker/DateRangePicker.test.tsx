import '@testing-library/jest-dom'

import { cleanup, render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { Provider } from 'kea'

import { DateRange } from '~/queries/schema/schema-general'
import { initKeaTests } from '~/test/init'

import { DateRangePicker, DateRangePickerProps } from './DateRangePicker'

const DEFAULT_RANGE: DateRange = { date_from: '-1h', date_to: null }

function renderPicker(overrides: Partial<DateRangePickerProps> = {}): { setDateRange: jest.Mock } {
    const setDateRange = jest.fn()
    render(
        <Provider>
            <DateRangePicker logicKey="test" dateRange={DEFAULT_RANGE} setDateRange={setDateRange} {...overrides} />
        </Provider>
    )
    return { setDateRange }
}

describe('DateRangePicker', () => {
    beforeEach(() => {
        initKeaTests()
    })

    afterEach(() => {
        cleanup()
    })

    it('renders the current range as the trigger label', () => {
        renderPicker()
        expect(screen.getByText('Last 1 hour')).toBeInTheDocument()
    })

    it('selects a preset and calls setDateRange', async () => {
        const { setDateRange } = renderPicker()

        await userEvent.click(screen.getByText('Last 1 hour'))
        // The preset list lives in a portaled popover overlay, so wait for it to
        // appear instead of assuming it rendered within the click's act() flush.
        await userEvent.click(await screen.findByText('5 minutes'))

        await waitFor(() => expect(setDateRange).toHaveBeenCalledWith({ date_from: '-5M', date_to: null }))
    })

    it.each<[string, string | undefined, boolean]>([
        ['hidden', undefined, false],
        ['shown', 'UTC', true],
    ])('timezone selector is %s when timezone props are %s', async (_label, timezone, shouldShow) => {
        renderPicker(timezone ? { timezone, onTimezoneChange: jest.fn() } : {})

        await userEvent.click(screen.getByText('Last 1 hour'))

        if (shouldShow) {
            expect(await screen.findByTestId('timezone-select')).toBeInTheDocument()
        } else {
            // Anchor on overlay content first, so the absence check can't pass
            // trivially against a not-yet-rendered popover.
            await screen.findByText('Custom range')
            expect(screen.queryByTestId('timezone-select')).not.toBeInTheDocument()
        }
    })
})
