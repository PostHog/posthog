import { eventUsageLogic } from 'lib/utils/eventUsageLogic'

import { initKeaTests } from '~/test/init'
import { PropertyFilterType, PropertyOperator } from '~/types'

import { webAnalyticsFilterLogic } from './webAnalyticsFilterLogic'

describe('webAnalyticsFilterLogic', () => {
    let logic: ReturnType<typeof webAnalyticsFilterLogic.build>

    beforeEach(() => {
        localStorage.clear()
        initKeaTests()
        eventUsageLogic.mount()
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

    it('includes non-stream property filters in liveFilters but excludes country and referrer', () => {
        const personFilter = {
            type: PropertyFilterType.Person as const,
            key: 'email',
            operator: PropertyOperator.IContains,
            value: 'posthog',
        }
        logic.actions.setWebAnalyticsFilters([personFilter])
        logic.actions.setCountryFilter('US')
        logic.actions.setReferrerFilter('google.com')

        expect(logic.values.liveFilters).toEqual([personFilter])
    })

    it('clearFilters resets property, device and domain filters', () => {
        logic.actions.setWebAnalyticsFilters([
            { type: PropertyFilterType.Person, key: 'email', operator: PropertyOperator.IContains, value: 'posthog' },
        ])
        logic.actions.setDeviceTypeFilter('Desktop')
        logic.actions.setDomainFilter('https://example.com')

        logic.actions.clearFilters()

        expect(logic.values.rawWebAnalyticsFilters).toEqual([])
        expect(logic.values.deviceTypeFilter).toBeNull()
        expect(logic.values.domainFilter).toBeNull()
    })
})
