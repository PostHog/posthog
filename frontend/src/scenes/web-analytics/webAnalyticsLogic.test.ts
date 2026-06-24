import { MOCK_DEFAULT_USER, MOCK_TEAM_ID } from 'lib/api.mock'

import { expectLogic } from 'kea-test-utils'

import api from 'lib/api'
import { FEATURE_FLAGS } from 'lib/constants'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { userLogic } from 'scenes/userLogic'

import { initKeaTests } from '~/test/init'
import { UserType } from '~/types'

import { ProductTab, TileId } from './common'
import { FOCUS_MODE_TILE_IDS } from './focus-mode/focusModeMapping'
import { WebAnalyticsConcern, getFocusModeOnboardingSeenKey } from './focus-mode/types'
import { webAnalyticsLogic } from './webAnalyticsLogic'

describe('webAnalyticsLogic focus mode', () => {
    let logic: ReturnType<typeof webAnalyticsLogic.build>

    const enableFocusMode = (): void => {
        featureFlagLogic.actions.setFeatureFlags([FEATURE_FLAGS.WEB_ANALYTICS_FOCUS_MODE], {
            [FEATURE_FLAGS.WEB_ANALYTICS_FOCUS_MODE]: 'test',
        })
    }

    beforeEach(() => {
        localStorage.clear()
        initKeaTests()
        jest.spyOn(api.propertyDefinitions, 'list').mockResolvedValue({ results: [] } as any)
        jest.spyOn(api.hogFunctions, 'list').mockResolvedValue({ results: [] } as any)
        jest.spyOn(api, 'update').mockResolvedValue({} as any)
        featureFlagLogic.mount()
        logic = webAnalyticsLogic()
        logic.mount()
    })

    afterEach(() => {
        logic.unmount()
        jest.restoreAllMocks()
    })

    it('applies selected concerns by updating hiddenTiles', async () => {
        enableFocusMode()
        logic.actions.openFocusModeModal()
        logic.actions.toggleFocusModeConcern(WebAnalyticsConcern.RETENTION)

        await expectLogic(logic, () => {
            logic.actions.applyFocusMode()
        }).toMatchValues({
            focusModeConcerns: [WebAnalyticsConcern.RETENTION],
            focusModeEnabled: true,
            focusModeModalOpen: false,
            hiddenTiles: FOCUS_MODE_TILE_IDS.filter((tileId) => ![TileId.OVERVIEW, TileId.RETENTION].includes(tileId)),
            isFocusModeActive: true,
        })
    })

    it('does not apply focus mode with an empty selection', async () => {
        enableFocusMode()
        logic.actions.setTileVisibility(TileId.GRAPHS, false)
        logic.actions.openFocusModeModal()

        await expectLogic(logic, () => {
            logic.actions.applyFocusMode()
        }).toMatchValues({
            focusModeConcerns: [],
            focusModeEnabled: false,
            focusModeModalOpen: true,
            hiddenTiles: [TileId.GRAPHS],
            isFocusModeActive: false,
        })
    })

    it('uses saved concerns when reopening focus mode settings', async () => {
        enableFocusMode()
        logic.actions.openFocusModeModal()
        logic.actions.toggleFocusModeConcern(WebAnalyticsConcern.RETENTION)
        logic.actions.applyFocusMode()

        await expectLogic(logic, () => {
            logic.actions.openFocusModeModal()
        }).toMatchValues({
            focusModeDraftConcerns: [WebAnalyticsConcern.RETENTION],
            focusModeModalOpen: true,
        })
    })

    it('exits focus mode without clearing saved concerns', async () => {
        enableFocusMode()
        logic.actions.openFocusModeModal()
        logic.actions.toggleFocusModeConcern(WebAnalyticsConcern.RETENTION)
        logic.actions.applyFocusMode()

        await expectLogic(logic, () => {
            logic.actions.exitFocusMode()
        }).toMatchValues({
            focusModeConcerns: [WebAnalyticsConcern.RETENTION],
            focusModeEnabled: false,
            hiddenTiles: [],
            isFocusModeActive: false,
        })
    })

    it('exits focus mode and preserves manually-hidden non-focus tiles', async () => {
        enableFocusMode()
        logic.actions.setTileVisibility(TileId.WEB_VITALS, false)
        logic.actions.openFocusModeModal()
        logic.actions.toggleFocusModeConcern(WebAnalyticsConcern.RETENTION)
        logic.actions.applyFocusMode()

        await expectLogic(logic, () => {
            logic.actions.exitFocusMode()
        }).toMatchValues({
            focusModeConcerns: [WebAnalyticsConcern.RETENTION],
            focusModeEnabled: false,
            hiddenTiles: [TileId.WEB_VITALS],
            isFocusModeActive: false,
        })
    })

    it('re-enters focus mode using saved concerns', async () => {
        enableFocusMode()
        logic.actions.setFocusModeConcerns([WebAnalyticsConcern.RETENTION])

        await expectLogic(logic, () => {
            logic.actions.enterFocusMode()
        }).toMatchValues({
            focusModeConcerns: [WebAnalyticsConcern.RETENTION],
            focusModeEnabled: true,
            hiddenTiles: FOCUS_MODE_TILE_IDS.filter((tileId) => ![TileId.OVERVIEW, TileId.RETENTION].includes(tileId)),
            isFocusModeActive: true,
        })
    })

    it('resetTileVisibility restores all tiles', async () => {
        logic.actions.setFocusModeEnabled(true)
        logic.actions.setTileVisibility(TileId.GRAPHS, false)

        await expectLogic(logic, () => {
            logic.actions.resetTileVisibility()
        }).toMatchValues({
            focusModeEnabled: false,
            hiddenTiles: [],
        })
    })

    it('hides focus mode when the feature flag is off', async () => {
        await expectLogic(logic).toMatchValues({
            productTab: ProductTab.ANALYTICS,
            showFocusMode: false,
        })
    })

    it('hides focus mode for the control variant', async () => {
        featureFlagLogic.actions.setFeatureFlags([FEATURE_FLAGS.WEB_ANALYTICS_FOCUS_MODE], {
            [FEATURE_FLAGS.WEB_ANALYTICS_FOCUS_MODE]: 'control',
        })
        await expectLogic(logic).toMatchValues({
            productTab: ProductTab.ANALYTICS,
            showFocusMode: false,
        })
    })

    describe('onboarding', () => {
        const loadUser = (hasSeenProductIntroFor: Record<string, boolean>): void => {
            userLogic.actions.loadUserSuccess({
                ...MOCK_DEFAULT_USER,
                has_seen_product_intro_for: hasSeenProductIntroFor,
            } as UserType)
        }

        it('auto-opens for an unseen user when the flag flips on, without marking it seen', async () => {
            loadUser({})

            await expectLogic(logic, () => {
                enableFocusMode()
            })
                .toDispatchActions(['openFocusModeOnboarding'])
                .toNotHaveDispatchedActions(['markFocusModeOnboardingSeen'])
                .toMatchValues({ focusModeOnboardingModalOpen: true })

            expect(api.update).not.toHaveBeenCalled()
        })

        it('does not auto-open when already seen', async () => {
            loadUser({ [getFocusModeOnboardingSeenKey(MOCK_TEAM_ID)]: true })

            await expectLogic(logic, () => {
                enableFocusMode()
            }).toMatchValues({ focusModeOnboardingModalOpen: false })
        })

        it('auto-opens when onboarding was only seen for a different project', async () => {
            loadUser({ [getFocusModeOnboardingSeenKey(MOCK_TEAM_ID + 1)]: true })

            await expectLogic(logic, () => {
                enableFocusMode()
            })
                .toDispatchActions(['openFocusModeOnboarding'])
                .toMatchValues({ focusModeOnboardingModalOpen: true })
        })

        it('does not auto-open when concerns already saved', async () => {
            loadUser({})
            logic.actions.setFocusModeConcerns([WebAnalyticsConcern.RETENTION])

            await expectLogic(logic, () => {
                enableFocusMode()
            }).toMatchValues({ focusModeOnboardingModalOpen: false })
        })

        it('does not auto-open when the user is not loaded', async () => {
            userLogic.actions.loadUserSuccess(null as any)

            await expectLogic(logic, () => {
                enableFocusMode()
            }).toMatchValues({ focusModeOnboardingModalOpen: false })
        })

        it('startFocusModeOnboarding closes the welcome modal, opens the real dialog, and marks it seen', async () => {
            loadUser({})
            enableFocusMode()
            logic.actions.openFocusModeOnboarding()
            ;(api.update as jest.Mock).mockClear()

            await expectLogic(logic, () => {
                logic.actions.startFocusModeOnboarding()
            }).toDispatchActions(['markFocusModeOnboardingSeen'])

            expect(logic.values.focusModeOnboardingModalOpen).toBe(false)
            expect(logic.values.focusModeModalOpen).toBe(true)
            expect(logic.values.focusModeModalIsOnboarding).toBe(true)

            expect(api.update).toHaveBeenCalledWith(
                expect.anything(),
                expect.objectContaining({
                    has_seen_product_intro_for: expect.objectContaining({
                        [getFocusModeOnboardingSeenKey(MOCK_TEAM_ID)]: true,
                    }),
                })
            )
        })

        it('dismissFocusModeOnboarding closes it and marks it seen', async () => {
            loadUser({})
            enableFocusMode()
            logic.actions.openFocusModeOnboarding()
            ;(api.update as jest.Mock).mockClear()

            await expectLogic(logic, () => {
                logic.actions.dismissFocusModeOnboarding()
            })
                .toDispatchActions(['markFocusModeOnboardingSeen'])
                .toMatchValues({ focusModeOnboardingModalOpen: false })

            expect(api.update).toHaveBeenCalledWith(
                expect.anything(),
                expect.objectContaining({
                    has_seen_product_intro_for: expect.objectContaining({
                        [getFocusModeOnboardingSeenKey(MOCK_TEAM_ID)]: true,
                    }),
                })
            )
        })

        it('manual openFocusModeModal() is not onboarding mode', async () => {
            await expectLogic(logic, () => {
                logic.actions.openFocusModeModal()
            }).toMatchValues({ focusModeModalIsOnboarding: false })
        })
    })
})

describe('webAnalyticsLogic precompute payload', () => {
    let logic: ReturnType<typeof webAnalyticsLogic.build>

    const setToggleFlag = (enabled: boolean): void => {
        featureFlagLogic.actions.setFeatureFlags(
            enabled ? [FEATURE_FLAGS.WEB_ANALYTICS_PRECOMPUTE_TOGGLE] : [],
            enabled ? { [FEATURE_FLAGS.WEB_ANALYTICS_PRECOMPUTE_TOGGLE]: true } : {}
        )
    }

    beforeEach(() => {
        localStorage.clear()
        initKeaTests()
        jest.spyOn(api.propertyDefinitions, 'list').mockResolvedValue({ results: [] } as any)
        jest.spyOn(api.hogFunctions, 'list').mockResolvedValue({ results: [] } as any)
        jest.spyOn(api, 'update').mockResolvedValue({} as any)
        featureFlagLogic.mount()
        logic = webAnalyticsLogic()
        logic.mount()
    })

    afterEach(() => {
        logic.unmount()
        jest.restoreAllMocks()
    })

    // `null`/`false` ignore the flag; only an explicit `true` is gated on it. With the flag off
    // an opt-in falls back to `undefined` (team default) rather than flipping to `false`, which
    // would wrongly opt an unrestricted team out.
    it.each([
        [null, true, undefined],
        [null, false, undefined],
        [true, true, true],
        [true, false, undefined],
        [false, true, false],
        [false, false, false],
    ])('toggle=%s flagOn=%s → payload %s', async (toggle, flagOn, expected) => {
        setToggleFlag(flagOn as boolean)
        logic.actions.setUseWebAnalyticsPrecompute(toggle as boolean | null)
        await expectLogic(logic).toMatchValues({
            controls: expect.objectContaining({ useWebAnalyticsPrecompute: expected }),
        })
    })
})
