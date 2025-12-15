import { expectLogic } from 'kea-test-utils'

import { DateFilterLogicProps, DateFilterView } from 'lib/components/DateFilter/types'
import { dayjs } from 'lib/dayjs'
import { dateMapping } from 'lib/utils'

import { dateFilterLogic } from './dateFilterLogic'

describe('dateFilterLogic', () => {
    let props: DateFilterLogicProps
    const onChange = jest.fn()
    let logic: ReturnType<typeof dateFilterLogic.build>

    beforeEach(async () => {
        dayjs.tz.setDefault('America/New_York')

        props = {
            key: 'test',
            onChange,
            dateFrom: null,
            dateTo: null,
            dateOptions: dateMapping,
            isDateFormatted: false,
        }
        logic = dateFilterLogic(props)
        logic.mount()
    })

    it('should only open one type of date filter', async () => {
        await expectLogic(logic).toMatchValues({
            isVisible: false,
            view: DateFilterView.QuickList,
        })
        logic.actions.open()
        await expectLogic(logic).toMatchValues({
            isVisible: true,
            view: DateFilterView.QuickList,
        })
        logic.actions.openFixedRange()
        await expectLogic(logic).toMatchValues({
            isVisible: true,
            view: DateFilterView.FixedRange,
        })
        logic.actions.openFixedRangeWithTime()
        await expectLogic(logic).toMatchValues({
            isVisible: true,
            view: DateFilterView.FixedRangeWithTime,
        })
        logic.actions.openDateToNow()
        await expectLogic(logic).toMatchValues({
            isVisible: true,
            view: DateFilterView.DateToNow,
        })
        logic.actions.close()
        await expectLogic(logic).toMatchValues({
            isVisible: false,
            view: DateFilterView.DateToNow,
        })
    })

    it('isFixedRangeWithTime is true when both dates have time precision', async () => {
        props = {
            key: 'test-time-precision',
            onChange,
            dateFrom: '2024-01-15T10:30:00',
            dateTo: '2024-01-16T14:45:00',
            dateOptions: dateMapping,
            isDateFormatted: false,
        }
        const withTimePrecision = dateFilterLogic(props)
        withTimePrecision.mount()

        await expectLogic(withTimePrecision).toMatchValues({
            isFixedRange: true,
            isFixedRangeWithTime: true,
            dateFromHasTimePrecision: true,
            dateToHasTimePrecision: true,
        })
    })

    it('isFixedRangeWithTime is false when dates have no time precision', async () => {
        props = {
            key: 'test-no-time-precision',
            onChange,
            dateFrom: '2024-01-15',
            dateTo: '2024-01-16',
            dateOptions: dateMapping,
            isDateFormatted: false,
        }
        const withoutTimePrecision = dateFilterLogic(props)
        withoutTimePrecision.mount()

        await expectLogic(withoutTimePrecision).toMatchValues({
            isFixedRange: true,
            isFixedRangeWithTime: false,
            dateFromHasTimePrecision: false,
            dateToHasTimePrecision: false,
        })
    })

    it('isFixedRangeWithTime is true when only dateFrom has time precision', async () => {
        props = {
            key: 'test-from-time-precision',
            onChange,
            dateFrom: '2024-01-15T10:30:00',
            dateTo: '2024-01-16',
            dateOptions: dateMapping,
            isDateFormatted: false,
        }
        const withFromTimePrecision = dateFilterLogic(props)
        withFromTimePrecision.mount()

        await expectLogic(withFromTimePrecision).toMatchValues({
            isFixedRange: true,
            isFixedRangeWithTime: true,
            dateFromHasTimePrecision: true,
            dateToHasTimePrecision: false,
        })
    })

    it('isFixedRangeWithTime is true when only dateTo has time precision', async () => {
        props = {
            key: 'test-to-time-precision',
            onChange,
            dateFrom: '2024-01-15',
            dateTo: '2024-01-16T14:45:00',
            dateOptions: dateMapping,
            isDateFormatted: false,
        }
        const withToTimePrecision = dateFilterLogic(props)
        withToTimePrecision.mount()

        await expectLogic(withToTimePrecision).toMatchValues({
            isFixedRange: true,
            isFixedRangeWithTime: true,
            dateFromHasTimePrecision: false,
            dateToHasTimePrecision: true,
        })
    })

    it('can set the date range', async () => {
        props = {
            key: 'test',
            onChange,
            dateFrom: '-1dStart',
            dateTo: '-1dEnd',
            dateOptions: dateMapping,
            isDateFormatted: false,
        }
        const withDateFrom = dateFilterLogic(props)
        withDateFrom.mount()

        await expectLogic(withDateFrom).toMatchValues({ dateFrom: '-1dStart', dateTo: '-1dEnd', label: 'Yesterday' })
        expect(onChange).not.toHaveBeenCalled()
    })

    it('can clear the date range', async () => {
        props = {
            key: 'test',
            onChange,
            dateFrom: '-1d',
            dateTo: null,
            dateOptions: dateMapping,
            isDateFormatted: false,
        }
        const withDateFrom = dateFilterLogic(props)
        withDateFrom.mount()

        await expectLogic(withDateFrom, () => {
            withDateFrom.actions.setDate(null, null)
        })
        expect(onChange).toHaveBeenCalledWith(null, null, false)
    })

    it('can receive Custom as date props', async () => {
        props = {
            key: 'test',
            onChange,
            dateFrom: null,
            dateTo: null,
            dateOptions: dateMapping,
            isDateFormatted: false,
        }
        const withoutDateFrom = dateFilterLogic(props)
        withoutDateFrom.mount()

        await expectLogic(withoutDateFrom).toMatchValues({
            dateFrom: null,
            dateTo: null,
            label: 'No date range override',
        })
        expect(onChange).not.toHaveBeenCalled()
    })
})
