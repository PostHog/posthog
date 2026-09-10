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
        await userEvent.click(screen.getByText('5 minutes'))

        expect(setDateRange).toHaveBeenCalledWith({ date_from: '-5M', date_to: null })
    })

    // The panel is portaled to the document body, so a link inside it that navigates without closing
    // the panel leaves it floating over the next screen.
    it('closes the panel when the availability notice asks for it', async () => {
        renderPicker({
            dataAvailabilityNotice: ({ closePicker }) => (
                <button type="button" onClick={closePicker}>
                    Change retention
                </button>
            ),
        })

        await userEvent.click(screen.getByText('Last 1 hour'))
        await userEvent.click(screen.getByText('Change retention'))

        await waitFor(() => expect(screen.queryByText('Change retention')).not.toBeInTheDocument())
    })

    it.each<[string, string | undefined, boolean]>([
        ['hidden', undefined, false],
        ['shown', 'UTC', true],
    ])('timezone selector is %s when timezone props are %s', async (_label, timezone, shouldShow) => {
        renderPicker(timezone ? { timezone, onTimezoneChange: jest.fn() } : {})

        await userEvent.click(screen.getByText('Last 1 hour'))

        if (shouldShow) {
            expect(screen.getByTestId('timezone-select')).toBeInTheDocument()
        } else {
            expect(screen.queryByTestId('timezone-select')).not.toBeInTheDocument()
        }
    })
})
