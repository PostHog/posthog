import '@testing-library/jest-dom'

import { cleanup, render, screen } from '@testing-library/react'
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

    it('hides the timezone selector when no timezone props are passed', async () => {
        renderPicker()

        await userEvent.click(screen.getByText('Last 1 hour'))

        expect(screen.queryByTestId('timezone-select')).not.toBeInTheDocument()
    })

    it('shows the timezone selector when timezone props are passed', async () => {
        const onTimezoneChange = jest.fn()
        renderPicker({ timezone: 'UTC', onTimezoneChange })

        await userEvent.click(screen.getByText('Last 1 hour'))

        expect(screen.getByTestId('timezone-select')).toBeInTheDocument()
    })
})
