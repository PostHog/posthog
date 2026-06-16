import { expectLogic } from 'kea-test-utils'

import { initKeaTests } from '~/test/init'

import {
    webAnalyticsAchievementsAcknowledgeCelebration,
    webAnalyticsAchievementsOverview,
} from 'products/web_analytics/frontend/generated/api'
import type { AchievementsListResponseApi } from 'products/web_analytics/frontend/generated/api.schemas'

import { webAnalyticsAchievementsLogic } from './webAnalyticsAchievementsLogic'

jest.mock('products/web_analytics/frontend/generated/api', () => ({
    webAnalyticsAchievementsOverview: jest.fn(),
    webAnalyticsAchievementsAcknowledgeCelebration: jest.fn().mockResolvedValue({ acknowledged: true }),
}))

const MOCK_OVERVIEW: AchievementsListResponseApi = {
    definitions: [],
    user_progress: [{ track_key: 'hog_streak', current_stage: 2, progress_value: 4, last_computed_at: null }],
    team_progress: [],
    pending_celebrations: [{ track_key: 'hog_streak', stage: 2, stage_name: 'Snuffler' }],
}

describe('webAnalyticsAchievementsLogic', () => {
    let logic: ReturnType<typeof webAnalyticsAchievementsLogic.build>

    beforeEach(() => {
        initKeaTests()
        ;(webAnalyticsAchievementsOverview as jest.Mock).mockResolvedValue(MOCK_OVERVIEW)
        logic = webAnalyticsAchievementsLogic()
        logic.mount()
    })

    afterEach(() => {
        logic?.unmount()
    })

    it('exposes progress and pending celebrations after loading', async () => {
        await expectLogic(logic, () => {
            logic.actions.loadAchievements()
        })
            .toDispatchActions(['loadAchievementsSuccess'])
            .toMatchValues({
                pendingCelebrations: [{ track_key: 'hog_streak', stage: 2, stage_name: 'Snuffler' }],
                uncelebratedPending: [{ track_key: 'hog_streak', stage: 2, stage_name: 'Snuffler' }],
            })
    })

    it('acknowledging a celebration marks it celebrated and clears it from uncelebratedPending', async () => {
        await expectLogic(logic, () => {
            logic.actions.loadAchievements()
        }).toDispatchActions(['loadAchievementsSuccess'])

        await expectLogic(logic, () => {
            logic.actions.acknowledgeCelebration('hog_streak', 2)
        }).toMatchValues({ uncelebratedPending: [] })

        expect(webAnalyticsAchievementsAcknowledgeCelebration).toHaveBeenCalledWith(expect.any(String), {
            track_key: 'hog_streak',
            stage: 2,
        })
    })
})
