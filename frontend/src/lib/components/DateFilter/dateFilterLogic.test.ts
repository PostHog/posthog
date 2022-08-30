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
            defaultValue: 'Last 7 days',
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

    it('should set a rolling date range', async () => {
        await expect(logic.values).toMatchObject({
            rangeDateFrom: null,
            rangeDateTo: dayjs().format('YYYY-MM-DD'),
            isFixedRange: false,
            isRollingDateRange: false, // -7d comes from dropdown
        })

        const fourDaysAgo = dayjs().subtract(4, 'd').startOf('day')
        logic.actions.setRangeDateFrom(fourDaysAgo)
        logic.actions.applyRange()
        await expect(logic.values).toMatchObject({
            rangeDateFrom: fourDaysAgo.toISOString(),
            rangeDateTo: dayjs().format('YYYY-MM-DD'),
            isFixedRange: false,
            isRollingDateRange: true,
        })
    })
})
