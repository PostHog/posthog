import { expectLogic } from 'kea-test-utils'

import { lemonToast } from 'lib/lemon-ui/LemonToast/LemonToast'

import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'

import type { AchievementsListResponseApi } from 'products/web_analytics/frontend/generated/api.schemas'

import { webAnalyticsAchievementsLogic } from './webAnalyticsAchievementsLogic'

const OVERVIEW_URL = '/api/projects/:team_id/web_analytics_achievements/overview/'
const ACKNOWLEDGE_URL = '/api/projects/:team_id/web_analytics_achievements/acknowledge_celebration/'
const PREFERENCES_URL = '/api/projects/:team_id/web_analytics_achievements/preferences/'

const MOCK_OVERVIEW: AchievementsListResponseApi = {
    definitions: [],
    user_progress: [
        { track_key: 'streak', current_stage: 2, progress_value: 4, last_computed_at: null, unlocked_at: {} },
    ],
    team_progress: [],
    pending_celebrations: [{ track_key: 'streak', stage: 2, stage_name: 'Warming up' }],
}

const mkStages = (thresholds: number[]): { stage: number; name: string; threshold: number }[] =>
    thresholds.map((threshold, index) => ({ stage: index + 1, name: `Stage ${index + 1}`, threshold }))

const def = (
    key: string,
    scope: 'user' | 'team',
    thresholds: number[]
): AchievementsListResponseApi['definitions'][number] => ({
    key,
    display_name: key,
    description: '',
    scope,
    is_experiment_track: false,
    stages: mkStages(thresholds),
})

const DEFS_OVERVIEW: AchievementsListResponseApi = {
    definitions: [
        def('explorer', 'user', [1, 15, 40, 100, 250]),
        def('detective', 'user', [1, 10, 50, 150, 500]),
        def('streak', 'user', [2, 4, 7, 14, 30]),
        def('traffic', 'team', [10000, 100000, 1000000, 10000000, 100000000]),
    ],
    user_progress: [
        { track_key: 'explorer', current_stage: 3, progress_value: 95, last_computed_at: 'x', unlocked_at: {} },
        { track_key: 'detective', current_stage: 1, progress_value: 5, last_computed_at: 'x', unlocked_at: {} },
        { track_key: 'streak', current_stage: 5, progress_value: 30, last_computed_at: 'x', unlocked_at: {} },
    ],
    team_progress: [
        { track_key: 'traffic', current_stage: 1, progress_value: 50000, last_computed_at: 'x', unlocked_at: {} },
    ],
    pending_celebrations: [],
}

describe('webAnalyticsAchievementsLogic', () => {
    let logic: ReturnType<typeof webAnalyticsAchievementsLogic.build>
    let lastAck: { track_key: string; stage: number } | null

    beforeEach(() => {
        lastAck = null
        jest.spyOn(lemonToast, 'success').mockReturnValue('mock-toast-id')
        initKeaTests()
        useMocks({
            get: {
                [OVERVIEW_URL]: () => [200, MOCK_OVERVIEW],
                [PREFERENCES_URL]: () => [200, { achievements_opt_out: false }],
            },
            post: {
                [ACKNOWLEDGE_URL]: async ({ request }) => {
                    lastAck = (await request.json()) as { track_key: string; stage: number }
                    return [200, { acknowledged: true }]
                },
            },
        })
        logic = webAnalyticsAchievementsLogic()
        logic.mount()
    })

    afterEach(() => {
        logic?.unmount()
        jest.restoreAllMocks()
    })

    it('exposes progress and pending celebrations after loading', async () => {
        await expectLogic(logic, () => {
            logic.actions.loadAchievements()
        })
            .toDispatchActions(['loadAchievementsSuccess'])
            .toMatchValues({
                pendingCelebrations: [{ track_key: 'streak', stage: 2, stage_name: 'Warming up' }],
            })
    })

    it('toasts and acknowledges each pending celebration on load', async () => {
        await expectLogic(logic, () => {
            logic.actions.loadAchievements()
        })
            .toDispatchActions(['loadAchievementsSuccess', 'acknowledgeCelebration', 'triggerConfetti'])
            .toFinishAllListeners()
            .toMatchValues({ uncelebratedPending: [], confettiNonce: 1 })

        expect(lemonToast.success).toHaveBeenCalledTimes(1)
        expect(lastAck).toEqual({ track_key: 'streak', stage: 2 })
    })

    it('does not re-toast or re-celebrate an already-celebrated unlock on a second load', async () => {
        await expectLogic(logic, () => {
            logic.actions.loadAchievements()
        })
            .toDispatchActions(['loadAchievementsSuccess'])
            .toFinishAllListeners()
        expect(lemonToast.success).toHaveBeenCalledTimes(1)

        ;(lemonToast.success as jest.Mock).mockClear()

        await expectLogic(logic, () => {
            logic.actions.loadAchievements()
        })
            .toDispatchActions(['loadAchievementsSuccess'])
            .toFinishAllListeners()
            .toMatchValues({ confettiNonce: 1 })
        expect(lemonToast.success).not.toHaveBeenCalled()
    })

    it('refetches on openModal and does not register a poll', async () => {
        await expectLogic(logic, () => {
            logic.actions.openModal()
        }).toDispatchActions(['openModal', 'loadAchievements'])
        expect((logic.cache as any).disposables?.registry.has('achievementsPoll')).toBe(false)
    })

    it('acknowledging a celebration marks it celebrated and clears it from uncelebratedPending', async () => {
        await expectLogic(logic, () => {
            logic.actions.loadAchievements()
        }).toDispatchActions(['loadAchievementsSuccess'])

        await expectLogic(logic, () => {
            logic.actions.acknowledgeCelebration('streak', 2)
        })
            .toDispatchActions(['acknowledgeCelebration', 'markCelebrated'])
            .toFinishAllListeners()
            .toMatchValues({ uncelebratedPending: [] })

        expect(lastAck).toEqual({ track_key: 'streak', stage: 2 })
    })

    it('sorts tracks by closeness to the next tier, with maxed tracks last', async () => {
        useMocks({ get: { [OVERVIEW_URL]: () => [200, DEFS_OVERVIEW] } })
        await expectLogic(logic, () => {
            logic.actions.loadAchievements()
        }).toDispatchActions(['loadAchievementsSuccess'])

        expect(logic.values.sortedUserTracks.map((track) => track.key)).toEqual(['explorer', 'detective', 'streak'])
        expect(logic.values.sortedTeamTracks.map((track) => track.key)).toEqual(['traffic'])
    })

    it('toggles expanded tracks and clears them when the modal closes', async () => {
        await expectLogic(logic, () => {
            logic.actions.toggleTrackExpanded('explorer')
        }).toMatchValues({ expandedTracks: ['explorer'] })

        logic.actions.toggleTrackExpanded('detective')
        expect(logic.values.expandedTracks).toEqual(['explorer', 'detective'])

        logic.actions.toggleTrackExpanded('explorer')
        expect(logic.values.expandedTracks).toEqual(['detective'])

        logic.actions.closeModal()
        expect(logic.values.expandedTracks).toEqual([])
    })
})
