import { render, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'

import { dayjs } from 'lib/dayjs'
import { range } from 'lib/utils/arrays'

import { getAllByDataAttr, getByDataAttr } from '~/test/byDataAttr'

import { LemonCalendar } from './LemonCalendar'

describe('LemonCalendar', () => {
    test('click and move between months with one month showing', async () => {
        const onLeftmostMonthChanged = jest.fn()
        const onDateClick = jest.fn()

        const { container } = render(
            <LemonCalendar
                leftmostMonth={dayjs('2020-02-01')}
                months={1}
                onLeftmostMonthChanged={onLeftmostMonthChanged}
                onDateClick={onDateClick}
            />
        )

        // find just one month
        const lemonCalendarMonths = getAllByDataAttr(container, 'lemon-calendar-month')
        expect(lemonCalendarMonths.length).toBe(1)
        const [calendar] = lemonCalendarMonths

        // make sure there are 5 weeks in the February 2020 calendar
        const lemonCalendarWeeks = getAllByDataAttr(container, 'lemon-calendar-week')
        expect(lemonCalendarWeeks.length).toBe(5)

        // find February 2020
        expect(await within(calendar).findByText('February 2020')).toBeTruthy()

        // go to January 2020
        const previousMonth = getByDataAttr(container, 'lemon-calendar-month-previous')
        await userEvent.click(previousMonth)
        expect(onLeftmostMonthChanged).toHaveBeenCalledWith(dayjs('2020-01-01'))
        expect(await within(calendar).findByText('January 2020')).toBeTruthy()

        // click on 15
        let fifteenth = await within(container).findByText('15')
        await userEvent.click(fifteenth)
        expect(onDateClick).toHaveBeenCalledWith(dayjs('2020-01-15'))

        // go to March 2020
        const nextMonth = getByDataAttr(container, 'lemon-calendar-month-next')
        await userEvent.click(nextMonth)
        await userEvent.click(nextMonth)
        expect(onLeftmostMonthChanged).toHaveBeenCalledWith(dayjs('2020-02-01'))
        expect(onLeftmostMonthChanged).toHaveBeenCalledWith(dayjs('2020-03-01'))
        expect(await within(calendar).findByText('March 2020')).toBeTruthy()

        // click on 15
        fifteenth = await within(container).findByText('15') // the cell moved
        await userEvent.click(fifteenth)
        expect(onDateClick).toHaveBeenCalledWith(dayjs('2020-03-15'))
    })

    test('click and move between months with two months showing', async () => {
        const onLeftmostMonthChanged = jest.fn()
        const onDateClick = jest.fn()

        const { container } = render(
            <LemonCalendar
                leftmostMonth={dayjs('2020-02-01')}
                months={2}
                onLeftmostMonthChanged={onLeftmostMonthChanged}
                onDateClick={onDateClick}
            />
        )

        // find just one month
        const lemonCalendars = getAllByDataAttr(container, 'lemon-calendar-month')
        expect(lemonCalendars.length).toBe(2)
        const [cal1, cal2] = lemonCalendars

        // find February 2020
        expect(await within(cal1).findByText('February 2020')).toBeTruthy()
        expect(await within(cal2).findByText('March 2020')).toBeTruthy()

        // go to January 2020
        const previousMonth = getByDataAttr(container, 'lemon-calendar-month-previous')
        await userEvent.click(previousMonth)
        expect(onLeftmostMonthChanged).toHaveBeenCalledWith(dayjs('2020-01-01'))
        expect(await within(cal1).findByText('January 2020')).toBeTruthy()
        expect(await within(cal2).findByText('February 2020')).toBeTruthy()

        // click on 15
        let fifteenth = await within(cal1).findByText('15')
        await userEvent.click(fifteenth)
        expect(onDateClick).toHaveBeenCalledWith(dayjs('2020-01-15'))

        // go to March 2020
        const nextMonth = getByDataAttr(container, 'lemon-calendar-month-next')
        await userEvent.click(nextMonth)
        await userEvent.click(nextMonth)
        expect(onLeftmostMonthChanged).toHaveBeenCalledWith(dayjs('2020-02-01'))
        expect(onLeftmostMonthChanged).toHaveBeenCalledWith(dayjs('2020-03-01'))
        expect(await within(cal1).findByText('March 2020')).toBeTruthy()
        expect(await within(cal2).findByText('April 2020')).toBeTruthy()

        // click on 15
        fifteenth = await within(cal1).findByText('15') // the cell moved
        await userEvent.click(fifteenth)
        expect(onDateClick).toHaveBeenCalledWith(dayjs('2020-03-15'))
    })

    test('renders many months', async () => {
        const { container } = render(<LemonCalendar months={10} />)
        const lemonCalendarMonths = getAllByDataAttr(container, 'lemon-calendar-month')
        expect(lemonCalendarMonths.length).toBe(10)
    })

    test('renders the current month by default', async () => {
        const onLeftmostMonthChanged = jest.fn()
        const onDateClick = jest.fn()

        const { container } = render(
            <LemonCalendar onLeftmostMonthChanged={onLeftmostMonthChanged} onDateClick={onDateClick} />
        )

        const calendar = getByDataAttr(container, 'lemon-calendar')
        const thisMonth = dayjs().format('MMMM YYYY')
        expect(await within(calendar).findByText(thisMonth)).toBeTruthy()
    })

    test('calls getDateState for each day with its date', async () => {
        const dates: dayjs.Dayjs[] = []
        render(
            <LemonCalendar
                leftmostMonth={dayjs('2020-02-20')}
                getDateState={({ date }) => {
                    dates.push(date)
                    return {}
                }}
            />
        )
        expect(dates.length).toBe(35)
        expect(dates).toEqual([
            dayjs('2020-01-26'),
            dayjs('2020-01-27'),
            dayjs('2020-01-28'),
            dayjs('2020-01-29'),
            dayjs('2020-01-30'),
            dayjs('2020-01-31'),
            dayjs('2020-02-01'),
            dayjs('2020-02-02'),
            dayjs('2020-02-03'),
            dayjs('2020-02-04'),
            dayjs('2020-02-05'),
            dayjs('2020-02-06'),
            dayjs('2020-02-07'),
            dayjs('2020-02-08'),
            dayjs('2020-02-09'),
            dayjs('2020-02-10'),
            dayjs('2020-02-11'),
            dayjs('2020-02-12'),
            dayjs('2020-02-13'),
            dayjs('2020-02-14'),
            dayjs('2020-02-15'),
            dayjs('2020-02-16'),
            dayjs('2020-02-17'),
            dayjs('2020-02-18'),
            dayjs('2020-02-19'),
            dayjs('2020-02-20'),
            dayjs('2020-02-21'),
            dayjs('2020-02-22'),
            dayjs('2020-02-23'),
            dayjs('2020-02-24'),
            dayjs('2020-02-25'),
            dayjs('2020-02-26'),
            dayjs('2020-02-27'),
            dayjs('2020-02-28'),
            dayjs('2020-02-29'),
        ])
    })

    test.each([
        ['selected', { selected: true }, 'LemonButton--primary'],
        ['range start', { isStart: true }, 'LemonCalendar__range--boundary'],
        ['range end', { isEnd: true }, 'LemonCalendar__range--boundary'],
        ['in range', { isBetween: true }, 'LemonButton--active'],
    ])('renders the %s date state as %j', async (_name, state, expectedClass) => {
        const { container } = render(
            <LemonCalendar
                leftmostMonth={dayjs('2020-02-01')}
                months={1}
                getDateState={({ date }) => (date.isSame('2020-02-14', 'd') ? state : {})}
            />
        )
        const fourteen = within(container).getByText('14').closest('[data-attr="lemon-calendar-day"]')
        expect(fourteen?.className.split(' ')).toContain(expectedClass)
    })

    test('disables a date when getDateState returns a disabledReason', async () => {
        const { container } = render(
            <LemonCalendar
                leftmostMonth={dayjs('2020-02-01')}
                months={1}
                getDateState={({ date }) => (date.isSame('2020-02-14', 'd') ? { disabledReason: 'nope' } : {})}
            />
        )
        const fourteen = within(container).getByText('14').closest('[data-attr="lemon-calendar-day"]')
        expect(fourteen?.getAttribute('aria-disabled')).toBe('true')
    })

    test('renders the default cell styling when no getDateState is given', async () => {
        const { container } = render(<LemonCalendar leftmostMonth={dayjs('2020-02-01')} months={1} />)
        // 30 only exists as a faded out-of-month (January) cell in the February grid
        const outOfMonth = within(container).getByText('30').closest('[data-attr="lemon-calendar-day"]')
        expect(outOfMonth?.className.split(' ')).toContain('opacity-25')
        const inMonth = within(container).getByText('15').closest('[data-attr="lemon-calendar-day"]')
        expect(inMonth?.className.split(' ')).toContain('flex-col')
        expect(inMonth?.className.split(' ')).not.toContain('opacity-25')
    })

    test('marks today with the today class', async () => {
        const { container } = render(<LemonCalendar />)
        expect(container.querySelector('.LemonCalendar__today')).toBeTruthy()
    })

    test('calls getTimeState for each time', async () => {
        const calls: any = []
        render(
            <LemonCalendar
                getTimeState={({ unit, value }) => {
                    calls.push([unit, value])
                    return {}
                }}
                granularity="minute"
            />
        )
        const minutes = range(0, 60).map((num) => ['m', num])
        expect(calls.length).toBe(74)
        expect(calls).toEqual([
            ['h', 12],
            ['h', 1],
            ['h', 2],
            ['h', 3],
            ['h', 4],
            ['h', 5],
            ['h', 6],
            ['h', 7],
            ['h', 8],
            ['h', 9],
            ['h', 10],
            ['h', 11],
            ...minutes,
            ['a', 'am'],
            ['a', 'pm'],
        ])
    })

    test('use24HourFormat renders 0-23 hours without AM/PM', async () => {
        const calls: any = []
        render(
            <LemonCalendar
                getTimeState={({ unit, value }) => {
                    calls.push([unit, value])
                    return {}
                }}
                granularity="minute"
                use24HourFormat
            />
        )
        const hours = range(0, 24).map((num) => ['h', num])
        const minutes = range(0, 60).map((num) => ['m', num])
        expect(calls.length).toBe(84) // 24 hours + 60 minutes, no AM/PM
        expect(calls).toEqual([...hours, ...minutes])
    })
})
