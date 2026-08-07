import { initKeaTests } from '~/test/init'
import { PropertyFilterType, PropertyOperator } from '~/types'

import { webAnalyticsFilterLogic } from './webAnalyticsFilterLogic'

describe('webAnalyticsFilterLogic', () => {
    let logic: ReturnType<typeof webAnalyticsFilterLogic.build>

    beforeEach(() => {
        localStorage.clear()
        initKeaTests()
        logic = webAnalyticsFilterLogic()
        logic.mount()
    })

    afterEach(() => {
        logic.unmount()
    })

    it('keeps the filter type when merging a second value into an existing filter', () => {
        logic.actions.togglePropertyFilter(PropertyFilterType.Session, '$entry_utm_medium', 'cpc')
        logic.actions.togglePropertyFilter(PropertyFilterType.Session, '$entry_utm_medium', 'paid')

        expect(logic.values.rawWebAnalyticsFilters).toEqual([
            {
                type: PropertyFilterType.Session,
                key: '$entry_utm_medium',
                operator: PropertyOperator.Exact,
                value: ['cpc', 'paid'],
            },
        ])
    })
})
