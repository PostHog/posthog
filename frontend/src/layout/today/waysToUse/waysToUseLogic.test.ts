import { MOCK_DEFAULT_USER } from 'lib/api.mock'

import { expectLogic } from 'kea-test-utils'

import { FEATURE_FLAGS } from 'lib/constants'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { sceneLogic } from 'scenes/sceneLogic'
import { Scene } from 'scenes/sceneTypes'
import { userLogic } from 'scenes/userLogic'
import { welcomeDialogLogic } from 'scenes/welcome/welcomeDialogLogic'

import { initKeaTests } from '~/test/init'
import { UserType } from '~/types'

import { WAYS_TO_USE_SEEN_KEY, WaysToUseEligibility, shouldOfferWaysToUse } from './waysToUse'
import { waysToUseLogic } from './waysToUseLogic'

const NOW = Date.parse('2026-10-16T12:00:00Z')

const user = (overrides: Partial<UserType> = {}): UserType =>
    ({
        ...MOCK_DEFAULT_USER,
        date_joined: '2026-10-15T09:00:00Z',
        has_seen_product_intro_for: {},
        ...overrides,
    }) as UserType

const eligibility = (overrides: Partial<WaysToUseEligibility> = {}): WaysToUseEligibility => ({
    todayRailEnabled: true,
    onHome: true,
    user: user(),
    welcomeDialogDue: false,
    now: NOW,
    ...overrides,
})

describe('waysToUse', () => {
    it('offers the dialog to a newcomer on Today home', () => {
        expect(shouldOfferWaysToUse(eligibility())).toBe(true)
    })

    it.each([
        ['the new web is off', { todayRailEnabled: false }],
        ['the user is on another page', { onHome: false }],
        ['the user has not loaded', { user: null }],
        ['the welcome dialog is due', { welcomeDialogDue: true }],
        ['the user closed it before', { user: user({ has_seen_product_intro_for: { [WAYS_TO_USE_SEEN_KEY]: true } }) }],
        ['the account is older than two weeks', { user: user({ date_joined: '2026-09-30T09:00:00Z' }) }],
    ])('does not offer the dialog when %s', (_label, overrides) => {
        expect(shouldOfferWaysToUse(eligibility(overrides))).toBe(false)
    })

    describe('logic', () => {
        let logic: ReturnType<typeof waysToUseLogic.build>

        beforeEach(() => {
            jest.useFakeTimers({ now: NOW })
            initKeaTests()
            featureFlagLogic.mount()
            featureFlagLogic.actions.setFeatureFlags([FEATURE_FLAGS.TODAY_RAIL_NAV], {
                [FEATURE_FLAGS.TODAY_RAIL_NAV]: true,
            })
            userLogic.mount()
            userLogic.actions.loadUserSuccess(user())
            sceneLogic.mount()
            logic = waysToUseLogic()
            logic.mount()
            jest.runOnlyPendingTimers()
        })

        afterEach(() => {
            jest.useRealTimers()
        })

        const openScene = (sceneKey: string): void => {
            sceneLogic.actions.setScene(Scene.ProjectHomepage, sceneKey, {
                params: {},
                searchParams: {},
                hashParams: {},
            })
        }

        it.each([
            ['opens on Today home', 'projectHomepage', true],
            ['stays closed over a Today report, which shares the home scene', 'todayReport', false],
        ])('%s', (_label, sceneKey, isOpen) => {
            openScene(sceneKey)
            expect(logic.values.isOpen).toBe(isOpen)
        })

        it.each([
            ['closed', () => welcomeDialogLogic.actions.markClosed('membership', NOW)],
            ['dismissed', () => welcomeDialogLogic.actions.markDismissed('membership')],
        ])('stays closed for the rest of the session once the welcome dialog was %s', (_label, closeWelcome) => {
            closeWelcome()
            openScene('projectHomepage')
            expect(logic.values.isOpen).toBe(false)
        })

        it('records the close against the user and keeps it closed', async () => {
            await expectLogic(logic, () => {
                logic.actions.closeWaysToUse('get_started')
            })
                .toDispatchActions([userLogic.actionCreators.updateHasSeenProductIntroFor(WAYS_TO_USE_SEEN_KEY)])
                .toMatchValues({ closed: true, isOpen: false })
        })
    })
})
