import React from 'react'
import { LemonCalendar } from './LemonCalendar'
import { render, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { getAllByDataAttr, getByDataAttr } from '~/test/byDataAttr'
import { dayjs } from 'lib/dayjs'

describe('LemonCalendar', () => {
    test('click and move between months with one month showing', async () => {
        const onLeftmostMonthChanged = jest.fn()
        const onDateClick = jest.fn()

        const { container } = render(
            <LemonCalendar
                leftmostMonth="2020-02-01"
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
        expect(await within(calendar).findByText('February 2020')).toBeDefined()

        // go to January 2020
        const previousMonth = getByDataAttr(container, 'lemon-calendar-month-previous')
        userEvent.click(previousMonth)
        expect(onLeftmostMonthChanged).toHaveBeenCalledWith('2020-01-01')
        expect(await within(calendar).findByText('January 2020')).toBeDefined()

        // click on 15
        let fifteenth = await within(container).findByText('15')
        userEvent.click(fifteenth)
        expect(onDateClick).toHaveBeenCalledWith('2020-01-15', '2020-01-01')

        // go to March 2020
        const nextMonth = getByDataAttr(container, 'lemon-calendar-month-next')
        userEvent.click(nextMonth)
        userEvent.click(nextMonth)
        expect(onLeftmostMonthChanged).toHaveBeenCalledWith('2020-02-01')
        expect(onLeftmostMonthChanged).toHaveBeenCalledWith('2020-03-01')
        expect(await within(calendar).findByText('March 2020')).toBeDefined()

        // click on 15
        fifteenth = await within(container).findByText('15') // the cell moved
        userEvent.click(fifteenth)
        expect(onDateClick).toHaveBeenCalledWith('2020-03-15', '2020-03-01')
    })

    test('click and move between months with two months showing', async () => {
        const onLeftmostMonthChanged = jest.fn()
        const onDateClick = jest.fn()

        const { container } = render(
            <LemonCalendar
                leftmostMonth="2020-02-01"
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
        expect(await within(cal1).findByText('February 2020')).toBeDefined()
        expect(await within(cal2).findByText('March 2020')).toBeDefined()

        // go to January 2020
        const previousMonth = getByDataAttr(container, 'lemon-calendar-month-previous')
        userEvent.click(previousMonth)
        expect(onLeftmostMonthChanged).toHaveBeenCalledWith('2020-01-01')
        expect(await within(cal1).findByText('January 2020')).toBeDefined()
        expect(await within(cal2).findByText('February 2020')).toBeDefined()

        // click on 15
        let fifteenth = await within(cal1).findByText('15')
        userEvent.click(fifteenth)
        expect(onDateClick).toHaveBeenCalledWith('2020-01-15', '2020-01-01')

        // go to March 2020
        const nextMonth = getByDataAttr(container, 'lemon-calendar-month-next')
        userEvent.click(nextMonth)
        userEvent.click(nextMonth)
        expect(onLeftmostMonthChanged).toHaveBeenCalledWith('2020-02-01')
        expect(onLeftmostMonthChanged).toHaveBeenCalledWith('2020-03-01')
        expect(await within(cal1).findByText('March 2020')).toBeDefined()
        expect(await within(cal2).findByText('April 2020')).toBeDefined()

        // click on 15
        fifteenth = await within(cal1).findByText('15') // the cell moved
        userEvent.click(fifteenth)
        expect(onDateClick).toHaveBeenCalledWith('2020-03-15', '2020-03-01')
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
        expect(await within(calendar).findByText(thisMonth)).toBeDefined()
    })

    test('calls getLemonButtonProps for each day', async () => {
        const calls: any = []
        const { container } = render(
            <LemonCalendar
                leftmostMonth="2020-02-20"
                getLemonButtonProps={(date, month, defaultProps) => {
                    const props = { ...defaultProps }
                    if (date === '2020-02-14') {
                        props['data-attr'] = 's6brap2ev'
                        props['className'] = 'yolo'
                    }
                    calls.push([date, month, props])
                    return props
                }}
            />
        )
        expect(calls.length).toBe(35)
        expect(calls).toEqual([
            ['2020-01-27', '2020-02-01', { className: 'flex-col opacity-25' }],
            ['2020-01-28', '2020-02-01', { className: 'flex-col opacity-25' }],
            ['2020-01-29', '2020-02-01', { className: 'flex-col opacity-25' }],
            ['2020-01-30', '2020-02-01', { className: 'flex-col opacity-25' }],
            ['2020-01-31', '2020-02-01', { className: 'flex-col opacity-25' }],
            ['2020-02-01', '2020-02-01', { className: 'flex-col' }],
            ['2020-02-02', '2020-02-01', { className: 'flex-col' }],
            ['2020-02-03', '2020-02-01', { className: 'flex-col' }],
            ['2020-02-04', '2020-02-01', { className: 'flex-col' }],
            ['2020-02-05', '2020-02-01', { className: 'flex-col' }],
            ['2020-02-06', '2020-02-01', { className: 'flex-col' }],
            ['2020-02-07', '2020-02-01', { className: 'flex-col' }],
            ['2020-02-08', '2020-02-01', { className: 'flex-col' }],
            ['2020-02-09', '2020-02-01', { className: 'flex-col' }],
            ['2020-02-10', '2020-02-01', { className: 'flex-col' }],
            ['2020-02-11', '2020-02-01', { className: 'flex-col' }],
            ['2020-02-12', '2020-02-01', { className: 'flex-col' }],
            ['2020-02-13', '2020-02-01', { className: 'flex-col' }],
            ['2020-02-14', '2020-02-01', { className: 'yolo', 'data-attr': 's6brap2ev' }],
            ['2020-02-15', '2020-02-01', { className: 'flex-col' }],
            ['2020-02-16', '2020-02-01', { className: 'flex-col' }],
            ['2020-02-17', '2020-02-01', { className: 'flex-col' }],
            ['2020-02-18', '2020-02-01', { className: 'flex-col' }],
            ['2020-02-19', '2020-02-01', { className: 'flex-col' }],
            ['2020-02-20', '2020-02-01', { className: 'flex-col' }],
            ['2020-02-21', '2020-02-01', { className: 'flex-col' }],
            ['2020-02-22', '2020-02-01', { className: 'flex-col' }],
            ['2020-02-23', '2020-02-01', { className: 'flex-col' }],
            ['2020-02-24', '2020-02-01', { className: 'flex-col' }],
            ['2020-02-25', '2020-02-01', { className: 'flex-col' }],
            ['2020-02-26', '2020-02-01', { className: 'flex-col' }],
            ['2020-02-27', '2020-02-01', { className: 'flex-col' }],
            ['2020-02-28', '2020-02-01', { className: 'flex-col' }],
            ['2020-02-29', '2020-02-01', { className: 'flex-col' }],
            ['2020-03-01', '2020-02-01', { className: 'flex-col opacity-25' }],
        ])
        const fourteen = getByDataAttr(container, 's6brap2ev')
        expect(fourteen).toBeDefined()
        expect(fourteen.className.split(' ')).toContain('yolo')
    })
})
