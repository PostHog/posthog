import { expectLogic } from 'kea-test-utils'

import { useMocks } from '~/mocks/jest'
import { QuickFilterContext } from '~/queries/schema/schema-general'
import { initKeaTests } from '~/test/init'

import { quickFiltersLogic } from './quickFiltersLogic'

describe('quickFiltersLogic', () => {
    let logic: ReturnType<typeof quickFiltersLogic.build>

    afterEach(() => {
        logic?.unmount()
    })

    it('falls back to an empty list when the request keeps failing', async () => {
        useMocks({
            get: {
                '/api/environments/:team_id/quick_filters/': () => [504],
            },
        })
        initKeaTests()
        logic = quickFiltersLogic({ context: QuickFilterContext.ErrorTrackingIssueFilters })
        logic.mount()

        await expectLogic(logic)
            .toDispatchActions(['loadQuickFilters', 'loadQuickFiltersSuccess'])
            .toMatchValues({ quickFilters: [] })
    })
})
