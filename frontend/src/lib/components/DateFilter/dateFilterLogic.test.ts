import { expectLogic } from 'kea-test-utils'
import { dayjs } from 'lib/dayjs'
import { dateMapping } from 'lib/utils'
import { dateFilterLogic, DateFilterLogicPropsType } from './dateFilterLogic'

describe('dateFilterLogic', () => {
    let props: DateFilterLogicPropsType
    const onChange = jest.fn()
    let logic: ReturnType<typeof dateFilterLogic.build>

    beforeEach(async () => {
        props = {
            key: 'test',
            defaultValue: '-7d',
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
        await expectLogic(logic).toMount().toMatchValues({
            isOpen: false,
            isDateRangeOpen: false,
        })

        logic.actions.open()
        await expectLogic(logic).toMatchValues({
            isOpen: true,
            isDateRangeOpen: false,
        })
        logic.actions.openDateRange()
        await expectLogic(logic).toMatchValues({
            isOpen: false,
            isDateRangeOpen: true,
        })
    })

    it('should set a rolling date range', async () => {
        await expect(logic.values).toMatchObject({
            rangeDateFrom: null,
            rangeDateTo: dayjs().format('YYYY-MM-DD'),
            isFixedDateRange: false,
            isRollingDateRange: true,
        })

        const threeDaysAgo = dayjs().subtract(3, 'd').format('YYYY-MM-DD')
        logic.actions.setRangeDateFrom(threeDaysAgo)
        await expect(logic.values).toMatchObject({
            rangeDateFrom: threeDaysAgo,
            rangeDateTo: dayjs().format('YYYY-MM-DD'),
            isFixedDateRange: false,
            isRollingDateRange: true,
        })
    })
})
