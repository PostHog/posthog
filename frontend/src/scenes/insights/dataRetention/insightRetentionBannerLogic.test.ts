import { expectLogic } from 'kea-test-utils'

import { insightDataLogic } from 'scenes/insights/insightDataLogic'

import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'
import { InsightShortId } from '~/types'

import { insightRetentionBannerLogic } from './insightRetentionBannerLogic'

const Insight123 = '123' as InsightShortId

describe('insightRetentionBannerLogic', () => {
    let logic: ReturnType<typeof insightRetentionBannerLogic.build>
    let dataLogic: ReturnType<typeof insightDataLogic.build>

    beforeEach(() => {
        useMocks({
            get: {
                '/api/environments/:team_id/insights/': { results: [{}] },
            },
        })
        initKeaTests()
        const props = { dashboardItemId: Insight123 }
        dataLogic = insightDataLogic(props)
        dataLogic.mount()
        logic = insightRetentionBannerLogic(props)
        logic.mount()
    })

    it.each([
        [{ results: [], events_retention_applied: true }, true],
        [{ results: [], events_retention_applied: false }, false],
        [{ results: [] }, false],
    ])('reads whether the server applied the retention floor from the response', async (response, expected) => {
        await expectLogic(logic, () => {
            dataLogic.actions.loadDataSuccess(response as any)
        }).toMatchValues({ retentionApplied: expected })
    })
})
