import { MOCK_DEFAULT_TEAM } from 'lib/api.mock'

import { FEATURE_FLAGS } from 'lib/constants'
import { lemonToast } from 'lib/lemon-ui/LemonToast'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { teamLogic } from 'scenes/teamLogic'

import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'
import { TeamType } from '~/types'

import type { RealtimeCohortsJoinStateEnumApi } from '../generated/api.schemas'
import { realtimeCohortsJoinLogic } from './realtimeCohortsJoinLogic'

function teamWithAccess(access: 'off' | 'serving'): TeamType {
    return { ...MOCK_DEFAULT_TEAM, realtime_cohorts: { access, cohorts_used: null, max_cohorts: null } }
}

function setRealtimeCohortsFlag(on: boolean): void {
    featureFlagLogic.actions.setFeatureFlags([], on ? { [FEATURE_FLAGS.REALTIME_COHORTS]: true } : {})
}

describe('realtimeCohortsJoinLogic', () => {
    let joins: number
    let accessReads: number
    let accessStates: (RealtimeCohortsJoinStateEnumApi | 'error')[]
    let readDelayMs: number

    // The mocked API answers on timers too, so settling flushes them without moving the clock.
    async function settle(): Promise<void> {
        for (let i = 0; i < 10; i++) {
            await jest.advanceTimersByTimeAsync(0)
        }
    }

    async function advance(ms: number): Promise<void> {
        await jest.advanceTimersByTimeAsync(ms)
        await settle()
    }

    async function mounted(
        access: 'off' | 'serving',
        flagOn: boolean
    ): Promise<ReturnType<typeof realtimeCohortsJoinLogic.build>> {
        initKeaTests(true, teamWithAccess(access))
        setRealtimeCohortsFlag(flagOn)
        const logic = realtimeCohortsJoinLogic()
        logic.mount()
        await settle()
        return logic
    }

    beforeEach(() => {
        jest.useFakeTimers()
        joins = 0
        accessReads = 0
        accessStates = ['setting_up']
        readDelayMs = 0
        useMocks({
            get: {
                '/api/projects/:team/realtime_cohorts/join/': async () => {
                    const state = accessStates[Math.min(accessReads, accessStates.length - 1)]
                    accessReads += 1
                    if (readDelayMs > 0) {
                        await new Promise((resolve) => setTimeout(resolve, readDelayMs))
                    }
                    return state === 'error' ? [500, {}] : [200, { state }]
                },
                '/api/projects/:team/': () => [200, teamWithAccess('serving')],
            },
            post: {
                '/api/projects/:team/realtime_cohorts/join/': () => {
                    joins += 1
                    return [200, { state: 'setting_up' }]
                },
            },
        })
    })

    afterEach(() => {
        window.IMPERSONATED_SESSION = undefined
        jest.useRealTimers()
        jest.restoreAllMocks()
    })

    it.each([
        ['an opted-in visit to a project that is off', 'off', true, false, 1, 1],
        ['the opt-in, which turns the flag on after the page loaded', 'off', false, false, 0, 1],
        ['a project that is serving', 'serving', true, false, 0, 0],
        ['an impersonated session', 'off', true, true, 0, 0],
    ] as const)(
        'joins only for an opted-in member of a project that is off, once per page load: %s',
        async (_name, access, flagOnAtMount, impersonated, joinsAtMount, joinsAfterFlagsReload) => {
            window.IMPERSONATED_SESSION = impersonated
            await mounted(access, flagOnAtMount)
            expect(joins).toBe(joinsAtMount)

            setRealtimeCohortsFlag(true)
            await settle()

            expect(joins).toBe(joinsAfterFlagsReload)
        }
    )

    it.each([
        ['setting_up', 'serving', 'serving', true],
        ['setting_up', 'failed', 'off', false],
        ['error', 'serving', 'serving', true],
    ] as const)('keeps polling after %s and stops on %s', async (firstAnswer, finalState, teamAccessAfter, toasted) => {
        accessStates = [firstAnswer, finalState]
        const toast = jest.spyOn(lemonToast, 'success')
        const logic = await mounted('off', true)
        expect(logic.values.joinState).toBe('setting_up')

        await advance(5000)
        expect([accessReads, logic.values.joinState]).toEqual([1, 'setting_up'])
        await advance(5000)
        await advance(30_000)

        expect(accessReads).toBe(2)
        expect(logic.values.joinState).toBe(finalState)
        expect(teamLogic.values.currentTeam?.realtime_cohorts?.access).toBe(teamAccessAfter)
        expect(toast).toHaveBeenCalledTimes(toasted ? 1 : 0)
    })

    it('waits for a slow answer before it reads again', async () => {
        accessStates = ['setting_up', 'serving']
        readDelayMs = 8000
        const logic = await mounted('off', true)

        await advance(12_000)
        expect(accessReads).toBe(1)
        await advance(20_000)

        expect([accessReads, logic.values.joinState]).toEqual([2, 'serving'])
    })
})
