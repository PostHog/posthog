import { render, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { dayjs } from 'lib/dayjs'
import { range } from 'lib/utils'

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
        userEvent.click(previousMonth)
        expect(onLeftmostMonthChanged).toHaveBeenCalledWith(dayjs('2020-01-01'))
        expect(await within(calendar).findByText('January 2020')).toBeTruthy()

        // click on 15
        let fifteenth = await within(container).findByText('15')
        userEvent.click(fifteenth)
        expect(onDateClick).toHaveBeenCalledWith(dayjs('2020-01-15'))

        // go to March 2020
        const nextMonth = getByDataAttr(container, 'lemon-calendar-month-next')
        userEvent.click(nextMonth)
        userEvent.click(nextMonth)
        expect(onLeftmostMonthChanged).toHaveBeenCalledWith(dayjs('2020-02-01'))
        expect(onLeftmostMonthChanged).toHaveBeenCalledWith(dayjs('2020-03-01'))
        expect(await within(calendar).findByText('March 2020')).toBeTruthy()

        // click on 15
        fifteenth = await within(container).findByText('15') // the cell moved
        userEvent.click(fifteenth)
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
        userEvent.click(previousMonth)
        expect(onLeftmostMonthChanged).toHaveBeenCalledWith(dayjs('2020-01-01'))
        expect(await within(cal1).findByText('January 2020')).toBeTruthy()
        expect(await within(cal2).findByText('February 2020')).toBeTruthy()

        // click on 15
        let fifteenth = await within(cal1).findByText('15')
        userEvent.click(fifteenth)
        expect(onDateClick).toHaveBeenCalledWith(dayjs('2020-01-15'))

        // go to March 2020
        const nextMonth = getByDataAttr(container, 'lemon-calendar-month-next')
        userEvent.click(nextMonth)
        userEvent.click(nextMonth)
        expect(onLeftmostMonthChanged).toHaveBeenCalledWith(dayjs('2020-02-01'))
        expect(onLeftmostMonthChanged).toHaveBeenCalledWith(dayjs('2020-03-01'))
        expect(await within(cal1).findByText('March 2020')).toBeTruthy()
        expect(await within(cal2).findByText('April 2020')).toBeTruthy()

        // click on 15
        fifteenth = await within(cal1).findByText('15') // the cell moved
        userEvent.click(fifteenth)
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

    test('calls getLemonButtonProps for each day', async () => {
        const calls: any = []
        const { container } = render(
            <LemonCalendar
                leftmostMonth={dayjs('2020-02-20')}
                getLemonButtonProps={({ date, props: defaultProps }) => {
                    const props = { ...defaultProps }
                    if (date.isSame('2020-02-14')) {
                        props['data-attr'] = 's6brap2ev'
                        props['className'] = 'yolo'
                    }
                    calls.push([date, props])
                    return props
                }}
            />
        )
        expect(calls.length).toBe(35)
        expect(calls).toEqual([
            [dayjs('2020-01-26'), { className: 'flex-col opacity-25' }],
            [dayjs('2020-01-27'), { className: 'flex-col opacity-25' }],
            [dayjs('2020-01-28'), { className: 'flex-col opacity-25' }],
            [dayjs('2020-01-29'), { className: 'flex-col opacity-25' }],
            [dayjs('2020-01-30'), { className: 'flex-col opacity-25' }],
            [dayjs('2020-01-31'), { className: 'flex-col opacity-25' }],
            [dayjs('2020-02-01'), { className: 'flex-col' }],
            [dayjs('2020-02-02'), { className: 'flex-col' }],
            [dayjs('2020-02-03'), { className: 'flex-col' }],
            [dayjs('2020-02-04'), { className: 'flex-col' }],
            [dayjs('2020-02-05'), { className: 'flex-col' }],
            [dayjs('2020-02-06'), { className: 'flex-col' }],
            [dayjs('2020-02-07'), { className: 'flex-col' }],
            [dayjs('2020-02-08'), { className: 'flex-col' }],
            [dayjs('2020-02-09'), { className: 'flex-col' }],
            [dayjs('2020-02-10'), { className: 'flex-col' }],
            [dayjs('2020-02-11'), { className: 'flex-col' }],
            [dayjs('2020-02-12'), { className: 'flex-col' }],
            [dayjs('2020-02-13'), { className: 'flex-col' }],
            [dayjs('2020-02-14'), { className: 'yolo', 'data-attr': 's6brap2ev' }],
            [dayjs('2020-02-15'), { className: 'flex-col' }],
            [dayjs('2020-02-16'), { className: 'flex-col' }],
            [dayjs('2020-02-17'), { className: 'flex-col' }],
            [dayjs('2020-02-18'), { className: 'flex-col' }],
            [dayjs('2020-02-19'), { className: 'flex-col' }],
            [dayjs('2020-02-20'), { className: 'flex-col' }],
            [dayjs('2020-02-21'), { className: 'flex-col' }],
            [dayjs('2020-02-22'), { className: 'flex-col' }],
            [dayjs('2020-02-23'), { className: 'flex-col' }],
            [dayjs('2020-02-24'), { className: 'flex-col' }],
            [dayjs('2020-02-25'), { className: 'flex-col' }],
            [dayjs('2020-02-26'), { className: 'flex-col' }],
            [dayjs('2020-02-27'), { className: 'flex-col' }],
            [dayjs('2020-02-28'), { className: 'flex-col' }],
            [dayjs('2020-02-29'), { className: 'flex-col' }],
        ])
        const fourteen = getByDataAttr(container, 's6brap2ev')
        expect(fourteen).toBeTruthy()
        expect(fourteen.className.split(' ')).toContain('yolo')
    })

    test('calls getLemonButtonTimeProps for each time', async () => {
        const calls: any = []
        render(
            <LemonCalendar
                getLemonButtonTimeProps={({ unit, value }) => {
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
})
