import { MOCK_TEAM_ID } from 'lib/api.mock'

import { expectLogic } from 'kea-test-utils'

import { initKeaTests } from '~/test/init'

import { marketingAnalyticsLogic } from './marketingAnalyticsLogic'

// Kea builds this from the reducer's path and name. It is pinned in the logic, so a rename cannot
// silently point the reducer at a different key and abandon what someone already saved.
const STORAGE_KEY = `${MOCK_TEAM_ID}__.scenes.webAnalytics.marketingAnalyticsLogic.integrationFilter`

describe('marketingAnalyticsLogic', () => {
    let logic: ReturnType<typeof marketingAnalyticsLogic.build>

    beforeEach(() => {
        localStorage.clear()
        initKeaTests()
    })

    afterEach(() => {
        if (logic?.cache.mounted) {
            logic.unmount()
        }
        localStorage.clear()
    })

    it('keeps the selection and drops an unknown key from a filter saved by an older build', async () => {
        localStorage.setItem(
            STORAGE_KEY,
            JSON.stringify({ integrationSourceIds: ['source-1'], includeNonIntegrated: true })
        )

        logic = marketingAnalyticsLogic()
        logic.mount()

        await expectLogic(logic).toMatchValues({
            integrationFilter: { integrationSourceIds: ['source-1'] },
        })
    })
})
