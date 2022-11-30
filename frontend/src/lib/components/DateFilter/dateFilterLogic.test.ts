import { expectLogic } from 'kea-test-utils'
import { dayjs } from 'lib/dayjs'
import { dateMapping } from 'lib/utils'
import { dateFilterLogic } from './dateFilterLogic'
import { DateFilterView, DateFilterLogicProps } from 'lib/components/DateFilter/types'

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

    it('can set the date range', async () => {
        props = {
            key: 'test',
            onChange,
            dateFrom: '-1dStart',
            dateTo: 'dStart',
            dateOptions: dateMapping,
            isDateFormatted: false,
        }
        const withDateFrom = dateFilterLogic(props)
        withDateFrom.mount()

        await expectLogic(withDateFrom).toMatchValues({ dateFrom: '-1dStart', dateTo: 'dStart', label: 'Yesterday' })
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
        expect(onChange).toHaveBeenCalledWith(null, null)
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

        await expectLogic(withoutDateFrom).toMatchValues({ dateFrom: null, dateTo: null, label: 'Custom' })
        expect(onChange).not.toHaveBeenCalled()
    })
})
