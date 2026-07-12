import { cleanup, render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'

import { DateRangeFilter, type DateRangePreset } from './DateRangeFilter'

const PRESETS: DateRangePreset<string>[] = [
    { id: '-7d', label: 'Last 7 days', value: '-7d', previewStart: (now) => new Date(now.getFullYear(), 0, 1) },
    { id: '-30d', label: 'Last 30 days', value: '-30d' },
]

describe('DateRangeFilter', () => {
    afterEach(cleanup)

    it('routes preset clicks through onPresetSelect, and an unedited calendar Apply keeps preset semantics', async () => {
        const onPresetSelect = jest.fn()
        const onCustomApply = jest.fn()
        render(
            <DateRangeFilter
                presets={PRESETS}
                selectedPresetId="-7d"
                onPresetSelect={onPresetSelect}
                onCustomApply={onCustomApply}
                trigger={<button>Dates</button>}
            />
        )

        await userEvent.click(screen.getByText('Dates'))
        await userEvent.click(screen.getByTitle('Last 30 days'))
        expect(onPresetSelect).toHaveBeenCalledTimes(1)
        expect(onPresetSelect.mock.calls[0][0]).toMatchObject({ id: '-30d', value: '-30d' })

        // Opening the calendar and applying without edits must NOT pin concrete dates —
        // the staged preset survives and the rolling range is preserved.
        await userEvent.click(screen.getByText('Dates'))
        await userEvent.click(screen.getByText('Custom range…'))
        await userEvent.click(screen.getByLabelText('Apply date range'))
        expect(onCustomApply).not.toHaveBeenCalled()
        expect(onPresetSelect).toHaveBeenCalledTimes(2)
        expect(onPresetSelect.mock.calls[1][0]).toMatchObject({ id: '-7d', value: '-7d' })
    })

    it('opens straight to the calendar when a custom range is active, and Apply commits concrete dates', async () => {
        const onPresetSelect = jest.fn()
        const onCustomApply = jest.fn()
        render(
            <DateRangeFilter
                presets={PRESETS}
                customActive
                customStart={new Date(2023, 0, 10)}
                customEnd={new Date(2023, 0, 20)}
                onPresetSelect={onPresetSelect}
                onCustomApply={onCustomApply}
                trigger={<button>Dates</button>}
            />
        )

        await userEvent.click(screen.getByText('Dates'))
        await userEvent.click(screen.getByLabelText('Apply date range'))

        expect(onCustomApply).toHaveBeenCalledTimes(1)
        expect(onCustomApply.mock.calls[0][0]).toEqual(new Date(2023, 0, 10))
        expect(onCustomApply.mock.calls[0][1]).toEqual(new Date(2023, 0, 20))
        expect(onPresetSelect).not.toHaveBeenCalled()
    })
})
