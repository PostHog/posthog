import { expectLogic } from 'kea-test-utils'

import { lemonToast } from 'lib/lemon-ui/LemonToast/LemonToast'

import { toPaginatedResponse } from '~/mocks/handlers'
import { useMocks } from '~/mocks/jest'
import { cohortsModel } from '~/models/cohortsModel'
import { initKeaTests } from '~/test/init'

import type { CohortRealtimeReadinessApi } from '../generated/api.schemas'
import { cohortRealtimeReadinessLogic } from './cohortRealtimeReadinessLogic'
import { REALTIME_POLL_INTERVAL_MS } from './realtimeReadiness'

jest.mock('lib/lemon-ui/LemonToast/LemonToast', () => ({
    lemonToast: { success: jest.fn(), error: jest.fn() },
}))

const readiness = (state: CohortRealtimeReadinessApi['state']): CohortRealtimeReadinessApi => ({
    state,
    ready_at: state === 'ready' ? '2026-11-17T10:20:00Z' : null,
    build: null,
    reason: null,
    history_limit_days: null,
})

const COHORT = {
    id: 1,
    name: 'Viewed pricing this week',
    is_static: false,
    filters: { properties: { type: 'AND', values: [] } },
    realtime_enabled: false,
    realtime: readiness('off'),
}

const setPageHidden = (hidden: boolean): void => {
    Object.defineProperty(document, 'hidden', { configurable: true, get: () => hidden })
    document.dispatchEvent(new Event('visibilitychange'))
}

describe('cohortRealtimeReadinessLogic', () => {
    let logic: ReturnType<typeof cohortRealtimeReadinessLogic.build>
    let listed: CohortRealtimeReadinessApi
    let served: CohortRealtimeReadinessApi | null
    let detailFetches: number

    async function mountLogic(): Promise<void> {
        cohortsModel.mount()
        await expectLogic(cohortsModel).toFinishAllListeners()
        logic = cohortRealtimeReadinessLogic({ cohortId: COHORT.id })
        logic.mount()
        await expectLogic(logic).toFinishAllListeners()
    }

    // expectLogic waits on real timers, so on a fake clock the requests are answered by moving the clock instead.
    async function mountLogicOnFakeClock(): Promise<void> {
        jest.useFakeTimers()
        cohortsModel.mount()
        await jest.advanceTimersByTimeAsync(0)
        logic = cohortRealtimeReadinessLogic({ cohortId: COHORT.id })
        logic.mount()
        await jest.advanceTimersByTimeAsync(0)
    }

    beforeEach(() => {
        listed = readiness('off')
        served = readiness('off')
        detailFetches = 0
        useMocks({
            get: {
                '/api/projects/:team_id/cohorts/': () => [200, toPaginatedResponse([{ ...COHORT, realtime: listed }])],
                '/api/projects/:team_id/cohorts/:id/': () => {
                    detailFetches += 1
                    return [200, { ...COHORT, realtime_enabled: served?.state !== 'off', realtime: served }]
                },
            },
        })
        initKeaTests()
    })

    afterEach(() => {
        logic?.unmount()
        jest.useRealTimers()
        jest.clearAllMocks()
        delete (document as any).hidden
    })

    it.each([
        { change: 'a teammate turned it on', listed: readiness('off'), served: readiness('building') },
        { change: 'it finished preparing', listed: readiness('building'), served: readiness('ready') },
    ])('reads the cohort again on mount, and shows that $change since the page loaded', async (states) => {
        listed = states.listed
        served = states.served

        await mountLogic()

        expect(detailFetches).toBe(1)
        expect(cohortsModel.values.cohortsById[COHORT.id]?.realtime).toEqual(states.served)
        // The build finished before this logic watched it, so it is not news.
        expect(lemonToast.success).not.toHaveBeenCalled()
    })

    it('reads the cohort again when the tab comes back, so an edit made in the cohort tab shows', async () => {
        await mountLogic()
        served = readiness('building')

        setPageHidden(true)
        setPageHidden(false)
        await expectLogic(logic).toFinishAllListeners()

        expect(detailFetches).toBe(2)
        expect(cohortsModel.values.cohortsById[COHORT.id]?.realtime?.state).toBe('building')
    })

    it('turns realtime on and puts the answer in the shared model the flag editor reads', async () => {
        let requestBody: unknown = null
        useMocks({
            post: {
                '/api/projects/:team_id/cohorts/:id/realtime/': async ({ request }) => {
                    requestBody = await request.json()
                    return [200, { ...COHORT, realtime_enabled: true, realtime: readiness('building') }]
                },
            },
        })
        await mountLogic()

        await expectLogic(logic, () => {
            logic.actions.turnOnRealtime()
        }).toDispatchActions(['turnOnRealtimeSuccess', 'refreshCurrentTeam'])

        expect(requestBody).toEqual({ enabled: true })
        expect(cohortsModel.values.cohortsById[COHORT.id]).toMatchObject({
            name: COHORT.name,
            realtime_enabled: true,
            realtime: readiness('building'),
        })
    })

    it('reloads the team when a turn-on is refused, because the plan limit it hit can come from newer usage', async () => {
        useMocks({
            post: {
                '/api/projects/:team_id/cohorts/:id/realtime/': () => [400, { detail: 'Your plan allows 5 cohorts.' }],
            },
        })
        await mountLogic()

        await expectLogic(logic, () => {
            logic.actions.turnOnRealtime()
        }).toDispatchActions(['turnOnRealtimeFailure', 'refreshCurrentTeam'])

        expect(cohortsModel.values.cohortsById[COHORT.id]?.realtime?.state).toBe('off')
    })

    it('drops a read that was in flight when realtime was turned on', async () => {
        let releaseRead: () => void = () => {}
        const readHeld = new Promise<void>((resolve) => {
            releaseRead = resolve
        })
        useMocks({
            get: {
                '/api/projects/:team_id/cohorts/:id/': async () => {
                    await readHeld
                    return [200, COHORT]
                },
            },
            post: {
                '/api/projects/:team_id/cohorts/:id/realtime/': {
                    ...COHORT,
                    realtime_enabled: true,
                    realtime: readiness('building'),
                },
            },
        })
        cohortsModel.mount()
        await expectLogic(cohortsModel).toFinishAllListeners()
        logic = cohortRealtimeReadinessLogic({ cohortId: COHORT.id })
        logic.mount()

        await expectLogic(logic, () => {
            logic.actions.turnOnRealtime()
        }).toDispatchActions(['turnOnRealtimeSuccess'])
        releaseRead()
        await expectLogic(logic).toFinishAllListeners()

        expect(cohortsModel.values.cohortsById[COHORT.id]?.realtime?.state).toBe('building')
    })

    it('keeps reading a cohort it turned on until it is ready, then stops and says so once', async () => {
        useMocks({
            post: {
                '/api/projects/:team_id/cohorts/:id/realtime/': {
                    ...COHORT,
                    realtime_enabled: true,
                    realtime: readiness('building'),
                },
            },
        })
        await mountLogicOnFakeClock()
        logic.actions.turnOnRealtime()
        await jest.advanceTimersByTimeAsync(0)
        const afterTurnOn = detailFetches

        // The API sends no readiness when its lookup of queued builds fails.
        served = null
        await jest.advanceTimersByTimeAsync(REALTIME_POLL_INTERVAL_MS)
        expect(detailFetches).toBe(afterTurnOn + 1)
        expect(cohortsModel.values.cohortsById[COHORT.id]?.realtime?.state).toBe('building')

        // The gap between the queued build and its run row reads as `needs_attention` for a build that is fine.
        served = readiness('needs_attention')
        await jest.advanceTimersByTimeAsync(REALTIME_POLL_INTERVAL_MS)
        expect(detailFetches).toBe(afterTurnOn + 2)

        served = readiness('ready')
        await jest.advanceTimersByTimeAsync(REALTIME_POLL_INTERVAL_MS)
        expect(detailFetches).toBe(afterTurnOn + 3)
        expect(cohortsModel.values.cohortsById[COHORT.id]?.realtime?.state).toBe('ready')

        await jest.advanceTimersByTimeAsync(REALTIME_POLL_INTERVAL_MS * 4)
        expect(detailFetches).toBe(afterTurnOn + 3)
        expect(lemonToast.success).toHaveBeenCalledTimes(1)
        expect(lemonToast.success).toHaveBeenCalledWith(
            "Cohort 'Viewed pricing this week' is ready. Feature flags can target it now."
        )
    })

    it('keeps reading a cohort the shared model shows as preparing when the first read lands in the gap', async () => {
        listed = readiness('building')
        served = readiness('needs_attention')

        await mountLogicOnFakeClock()
        const afterMount = detailFetches
        await jest.advanceTimersByTimeAsync(REALTIME_POLL_INTERVAL_MS)

        expect(detailFetches).toBe(afterMount + 1)
    })
})
