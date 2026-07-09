import { render, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { useState } from 'react'

import { dayjs } from 'lib/dayjs'
import {
    LemonCalendarSelect,
    LemonCalendarSelectProps,
    getTimeElement,
} from 'lib/lemon-ui/LemonCalendar/LemonCalendarSelect'

import { getByDataAttr } from '~/test/byDataAttr'

import { GetTimeStateOpts } from './LemonCalendar'

const createClickHelpers = (
    container: HTMLElement
): {
    clickOnDate: (day: string) => Promise<void>
    clickOnTime: (props: GetTimeStateOpts) => Promise<void>
} => ({
    clickOnDate: async (day: string): Promise<void> => {
        const element = container.querySelector('.LemonCalendar__month') as HTMLElement
        if (element) {
            await userEvent.click(await within(element).findByText(day))
            await userEvent.click(getByDataAttr(container, 'lemon-calendar-select-apply'))
        }
    },
    clickOnTime: async (props: GetTimeStateOpts): Promise<void> => {
        const element = getTimeElement(container.querySelector('.LemonCalendar__time'), props)
        if (element) {
            await userEvent.click(element)
            await userEvent.click(getByDataAttr(container, 'lemon-calendar-select-apply'))
        }
    },
})

const renderLemonCalendarSelect = (
    selectedDate: dayjs.Dayjs | null = null,
    props: Partial<LemonCalendarSelectProps> = {}
): {
    container: HTMLElement
    onClose: jest.Mock
    onChange: jest.Mock
    clickOnDate: (day: string) => Promise<void>
    clickOnTime: (props: GetTimeStateOpts) => Promise<void>
} => {
    const onClose = jest.fn()
    const onChange = jest.fn()

    function TestSelect(): JSX.Element {
        const [value, setValue] = useState<dayjs.Dayjs | null>(selectedDate)
        return (
            <LemonCalendarSelect
                months={1}
                value={value}
                onClose={onClose}
                onChange={(value) => {
                    setValue(value)
                    onChange(value)
                }}
                {...props}
            />
        )
    }

    const { container } = render(<TestSelect />)
    return { container, onClose, onChange, ...createClickHelpers(container) }
}

describe('LemonCalendarSelect', () => {
    beforeEach(() => {
        window.HTMLElement.prototype.scrollIntoView = jest.fn()

        jest.useFakeTimers({ advanceTimers: true }).setSystemTime(new Date('2023-01-10 17:22:08'))
    })

    afterEach(() => {
        jest.restoreAllMocks()
        jest.useRealTimers()
    })

    test('select various dates', async () => {
        const { container, onClose, onChange, clickOnDate } = renderLemonCalendarSelect(dayjs('2022-02-10'))

        // find just one month
        const calendar = getByDataAttr(container, 'lemon-calendar')
        expect(calendar).toBeTruthy()

        // find February 2022
        expect(await within(calendar).findByText('February 2022')).toBeTruthy()

        // click on 15
        await clickOnDate('15')
        expect(onChange).toHaveBeenCalledWith(dayjs('2022-02-15'))

        // click on 27
        await clickOnDate('27')
        expect(onChange).toHaveBeenCalledWith(dayjs('2022-02-27'))

        await userEvent.click(getByDataAttr(container, 'lemon-calendar-select-cancel'))
        expect(onClose).toHaveBeenCalled()
    })

    test('select various times', async () => {
        const { onChange, clickOnDate, clickOnTime } = renderLemonCalendarSelect(null, {
            granularity: 'minute',
        })

        // click on hour 8
        await clickOnDate('15')
        // sets the date to 15, hour and minutes to current time, and seconds to 0
        expect(onChange).toHaveBeenCalledWith(dayjs('2023-01-15T17:22:00.000Z'))

        // click on minute 42
        await clickOnTime({ unit: 'm', value: 42 })
        // sets the minutes but leaves all other values unchanged
        expect(onChange).toHaveBeenCalledWith(dayjs('2023-01-15T17:42:00.000Z'))

        // click on 'am'
        await clickOnTime({ unit: 'a', value: 'am' })
        // subtracts 12 hours from the time
        expect(onChange).toHaveBeenCalledWith(dayjs('2023-01-15T05:42:00.000Z'))

        // click on hour 8
        await clickOnTime({ unit: 'h', value: 8 })
        // only changes the hour
        expect(onChange).toHaveBeenCalledWith(dayjs('2023-01-15T08:42:00.000Z'))
    })

    test('only allow upcoming selection', async () => {
        const { onChange, clickOnDate, clickOnTime } = renderLemonCalendarSelect(null, {
            granularity: 'minute',
            selectionPeriod: 'upcoming',
        })

        // click on minute
        await clickOnTime({ unit: 'm', value: 42 })
        // time is disabled until a date is clicked
        expect(onChange).not.toHaveBeenCalled()

        // click on past date
        await clickOnDate('9')
        // cannot select a date in the past
        expect(onChange).not.toHaveBeenCalled()

        // click on current date
        await clickOnDate('10')
        // chooses the current date and sets the time to the current hour and minute
        expect(onChange).toHaveBeenCalledWith(dayjs('2023-01-10T17:22:00.000Z'))

        // click on an earlier hour
        await clickOnTime({ unit: 'a', value: 'am' })
        // does not update the date because it is in the past
        expect(onChange).toHaveBeenLastCalledWith(dayjs('2023-01-10T17:22:00.000Z'))

        // click on a later hour
        await clickOnTime({ unit: 'h', value: '8' })
        // updates the hour to 8pm (later than 5pm)
        expect(onChange).toHaveBeenLastCalledWith(dayjs('2023-01-10T20:22:00.000Z'))
    })

    test('upcoming selection uses selectionPeriodTimezone for the boundary', async () => {
        // 17:22 UTC is 12:22 in New York, so a same-day 2pm slot is still upcoming there.
        const { onChange, clickOnDate, clickOnTime } = renderLemonCalendarSelect(null, {
            granularity: 'minute',
            selectionPeriod: 'upcoming',
            selectionPeriodTimezone: 'America/New_York',
        })

        await clickOnDate('10')
        expect(onChange).toHaveBeenCalledWith(dayjs('2023-01-10T12:22:00.000Z'))

        await clickOnTime({ unit: 'h', value: '2' })
        expect(onChange).toHaveBeenLastCalledWith(dayjs('2023-01-10T14:22:00.000Z'))
    })

    test('upcoming selection resolves the day boundary in selectionPeriodTimezone', async () => {
        // 04:00 UTC on Jan 11 is still 23:00 on Jan 10 in New York, so "today" is Jan 10 there, not Jan 11 UTC.
        jest.setSystemTime(new Date('2023-01-11 04:00:00'))
        const { onChange, clickOnDate } = renderLemonCalendarSelect(null, {
            granularity: 'minute',
            selectionPeriod: 'upcoming',
            selectionPeriodTimezone: 'America/New_York',
        })

        // Jan 10 is today in New York, so it stays selectable (UTC-local would wrongly block it as past).
        await clickOnDate('10')
        expect(onChange).toHaveBeenCalledWith(dayjs('2023-01-10T23:00:00.000Z'))
    })

    test('past selection resolves the day boundary in selectionPeriodTimezone', async () => {
        // 20:00 UTC on Jan 10 is already 05:00 on Jan 11 in Tokyo, so "today" is Jan 11 there, not Jan 10 UTC.
        jest.setSystemTime(new Date('2023-01-10 20:00:00'))
        const { onChange, clickOnDate } = renderLemonCalendarSelect(null, {
            granularity: 'minute',
            selectionPeriod: 'past',
            selectionPeriodTimezone: 'Asia/Tokyo',
        })

        // Jan 11 is today in Tokyo, so it stays selectable in past mode (UTC-local would wrongly block it as future).
        await clickOnDate('11')
        expect(onChange).toHaveBeenCalledWith(dayjs('2023-01-11T05:00:00.000Z'))

        // Jan 12 is genuinely in the future in Tokyo and remains disabled.
        await clickOnDate('12')
        expect(onChange).toHaveBeenLastCalledWith(dayjs('2023-01-11T05:00:00.000Z'))
    })

    test('only allow past selection', async () => {
        const { onChange, clickOnDate, clickOnTime } = renderLemonCalendarSelect(null, {
            granularity: 'minute',
            selectionPeriod: 'past',
        })

        // click on minute
        await clickOnTime({ unit: 'm', value: 12 })
        // time is disabled until a date is clicked
        expect(onChange).not.toHaveBeenCalled()

        // click on future date
        await clickOnDate('11')
        // cannot select a date in the future
        expect(onChange).not.toHaveBeenCalled()

        // click on current date
        await clickOnDate('10')
        // chooses the current date and sets the time to the current hour and minute
        expect(onChange).toHaveBeenCalledWith(dayjs('2023-01-10T17:22:00.000Z'))

        // click on an later hour
        await clickOnTime({ unit: 'h', value: '18' })
        // does not update the date because it is in the future
        expect(onChange).toHaveBeenLastCalledWith(dayjs('2023-01-10T17:22:00.000Z'))

        // click on an earlier hour
        await clickOnTime({ unit: 'h', value: '2' })
        // updates the hour to 2pm (earlier than 5pm)
        expect(onChange).toHaveBeenLastCalledWith(dayjs('2023-01-10T14:22:00.000Z'))
    })

    test('select times with use24HourFormat', async () => {
        const { onChange, clickOnDate, clickOnTime } = renderLemonCalendarSelect(null, {
            granularity: 'minute',
            use24HourFormat: true,
        })

        // click on a date first
        await clickOnDate('15')
        // sets the date to 15, hour and minutes to current time, and seconds to 0
        expect(onChange).toHaveBeenCalledWith(dayjs('2023-01-15T17:22:00.000Z'))

        // click on hour 8 (should be 08:00, not adjusted for AM/PM)
        await clickOnTime({ unit: 'h', value: 8 })
        expect(onChange).toHaveBeenCalledWith(dayjs('2023-01-15T08:22:00.000Z'))

        // click on hour 20 (should be 20:00, only possible in 24h mode)
        await clickOnTime({ unit: 'h', value: 20 })
        expect(onChange).toHaveBeenCalledWith(dayjs('2023-01-15T20:22:00.000Z'))

        // click on hour 0 (midnight, only possible in 24h mode)
        await clickOnTime({ unit: 'h', value: 0 })
        expect(onChange).toHaveBeenCalledWith(dayjs('2023-01-15T00:22:00.000Z'))

        // click on minute 45
        await clickOnTime({ unit: 'm', value: 45 })
        expect(onChange).toHaveBeenCalledWith(dayjs('2023-01-15T00:45:00.000Z'))
    })
})
