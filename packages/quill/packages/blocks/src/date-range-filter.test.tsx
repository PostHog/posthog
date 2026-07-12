import { cleanup, render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'

import { DateRangeFilter, type DateRangeFilterPreset } from './date-range-filter'

const PRESETS: DateRangeFilterPreset<string>[] = [
    { id: '7d', label: 'Last 7 days', value: '-7d', previewStart: (now) => new Date(now.getFullYear(), 0, 1) },
    { id: '30d', label: 'Last 30 days', value: '-30d' },
]

describe('DateRangeFilter', () => {
    afterEach(cleanup)

    it('applies a preset on click, couriering its value payload, and closes the popover', async () => {
        const onPresetSelect = jest.fn()
        render(
            <DateRangeFilter label="Dates" presets={PRESETS} onPresetSelect={onPresetSelect} defaultOpen />
        )

        await userEvent.click(screen.getByText('Last 30 days'))

        expect(onPresetSelect).toHaveBeenCalledTimes(1)
        expect(onPresetSelect.mock.calls[0][0]).toMatchObject({ id: '30d', value: '-30d' })
        await waitFor(() => expect(screen.queryByText('Last 7 days')).toBeNull())
    })

    it('reveals the calendar behind the custom row, applies concrete dates, and cancel returns to the list', async () => {
        const onCustomApply = jest.fn()
        render(
            <DateRangeFilter
                label="Dates"
                presets={PRESETS}
                selectedPresetId="7d"
                onPresetSelect={jest.fn()}
                onCustomApply={onCustomApply}
                defaultOpen
            />
        )

        await userEvent.click(screen.getByText('Custom range…'))
        expect(screen.queryByText('Last 7 days')).toBeNull()

        await userEvent.click(screen.getByLabelText('Cancel'))
        expect(screen.getByText('Last 7 days')).not.toBeNull()
        expect(onCustomApply).not.toHaveBeenCalled()

        await userEvent.click(screen.getByText('Custom range…'))
        await userEvent.click(screen.getByLabelText('Apply date range'))
        expect(onCustomApply).toHaveBeenCalledTimes(1)
        const [start, end] = onCustomApply.mock.calls[0]
        expect(start).toBeInstanceOf(Date)
        expect(end).toBeInstanceOf(Date)
        expect(start.getTime()).toBeLessThanOrEqual(end.getTime())
    })

    it('opens straight to the calendar when a custom range is active', async () => {
        render(
            <DateRangeFilter
                label="Dates"
                presets={PRESETS}
                customActive
                customStart={new Date(2023, 0, 10)}
                customEnd={new Date(2023, 0, 20)}
                onPresetSelect={jest.fn()}
                onCustomApply={jest.fn()}
            />
        )

        await userEvent.click(screen.getByText('Dates'))

        expect(screen.queryByText('Last 7 days')).toBeNull()
        expect(screen.getByLabelText('Apply date range')).not.toBeNull()
    })

    it('renders listFooter in the list view only', async () => {
        render(
            <DateRangeFilter
                label="Dates"
                presets={PRESETS}
                onPresetSelect={jest.fn()}
                onCustomApply={jest.fn()}
                listFooter={<div>Footer controls</div>}
                defaultOpen
            />
        )

        expect(screen.getByText('Footer controls')).not.toBeNull()

        await userEvent.click(screen.getByText('Custom range…'))
        expect(screen.queryByText('Footer controls')).toBeNull()
    })
})
