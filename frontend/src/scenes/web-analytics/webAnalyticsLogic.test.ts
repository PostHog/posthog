import { MOCK_DEFAULT_USER, MOCK_TEAM_ID } from 'lib/api.mock'

import { router } from 'kea-router'
import { expectLogic } from 'kea-test-utils'
import posthog from 'posthog-js'

import api from 'lib/api'
import { FEATURE_FLAGS } from 'lib/constants'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { userLogic } from 'scenes/userLogic'

import { initKeaTests } from '~/test/init'
import { PropertyFilterType, PropertyOperator, UserType } from '~/types'

import { botAnalyticsLogic } from './botAnalyticsLogic'
import { GraphsTab, ProductTab, TileId } from './common'
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

describe('webAnalyticsLogic compare filter', () => {
    let logic: ReturnType<typeof webAnalyticsLogic.build>

    beforeEach(() => {
        localStorage.clear()
        initKeaTests()
        jest.spyOn(api.propertyDefinitions, 'list').mockResolvedValue({ results: [] } as any)
        jest.spyOn(api.hogFunctions, 'list').mockResolvedValue({ results: [] } as any)
        jest.spyOn(api, 'update').mockResolvedValue({} as any)
        ;(posthog as any).setPersonProperties = jest.fn()
        featureFlagLogic.mount()
        logic = webAnalyticsLogic()
        logic.mount()
    })

    afterEach(() => {
        logic.unmount()
        jest.restoreAllMocks()
    })

    // An all-time range has no earlier period, and comparing against one made the tiles report the
    // first day of data as the previous period's total. The stored preference has to survive the
    // switch, so that returning to a bounded range compares again without the user re-enabling it.
    it('drops the comparison for an all-time range and applies it again for a bounded one', async () => {
        logic.actions.setCompareFilter({ compare: true })

        logic.actions.setDates('all', null)
        await expectLogic(logic).toMatchValues({ compareFilter: { compare: false } })

        logic.actions.setDates('-7d', null)
        await expectLogic(logic).toMatchValues({ compareFilter: { compare: true } })
    })
})

describe('webAnalyticsLogic URL restoration', () => {
    let logic: ReturnType<typeof webAnalyticsLogic.build>

    beforeEach(() => {
        localStorage.clear()
        initKeaTests()
        jest.spyOn(api.propertyDefinitions, 'list').mockResolvedValue({ results: [] } as any)
        jest.spyOn(api.hogFunctions, 'list').mockResolvedValue({ results: [] } as any)
        jest.spyOn(api, 'update').mockResolvedValue({} as any)
        ;(posthog as any).setPersonProperties = jest.fn()
        featureFlagLogic.mount()
        logic = webAnalyticsLogic()
        logic.mount()
    })

    afterEach(() => {
        logic.unmount()
        jest.restoreAllMocks()
    })

    // These lock the full URL <-> state contract so the restore path can be refactored (centralising
    // the per-action dispatches into a single un-mapped sync) without silently regressing it:
    //  - every param restores into the right reducer (incl. state owned by the connected filter logic),
    //  - restoration does not thrash the URL (the actionToUrl <-> urlToAction cascade),
    //  - the bots tab keeps its flag-gating and last-day date default,
    //  - actionToUrl still mirrors user changes back into the URL.
    it.each<[string, Record<string, string>, () => unknown, unknown]>([
        ['device_tab', { device_tab: 'BROWSER' }, () => logic.values._deviceTab, 'BROWSER'],
        ['source_tab', { source_tab: 'REFERRING_DOMAIN' }, () => logic.values._sourceTab, 'REFERRING_DOMAIN'],
        ['path_tab', { path_tab: 'INITIAL_PATH' }, () => logic.values._pathTab, 'INITIAL_PATH'],
        ['graphs_tab', { graphs_tab: 'UNIQUE_USERS' }, () => logic.values._graphsTab, 'UNIQUE_USERS'],
        ['geography_tab', { geography_tab: 'MAP' }, () => logic.values._geographyTab, 'MAP'],
        ['active_hours_tab', { active_hours_tab: 'UNIQUE' }, () => logic.values._activeHoursTab, 'UNIQUE'],
        ['path_cleaning', { path_cleaning: 'false' }, () => logic.values._isPathCleaningEnabled, false],
        ['filter_test_accounts', { filter_test_accounts: 'true' }, () => logic.values.shouldFilterTestAccounts, true],
        ['include_host_path', { include_host_path: 'true' }, () => logic.values.includeHostPath, true],
        ['percentile', { percentile: 'p99' }, () => logic.values.webVitalsPercentile, 'p99'],
        // domain and device_type are owned by the connected webAnalyticsFilterLogic, so these also lock
        // restoration of cross-logic state.
        ['domain', { domain: 'example.com' }, () => logic.values.domainFilter, 'example.com'],
        ['device_type', { device_type: 'Desktop' }, () => logic.values.deviceTypeFilter, 'Desktop'],
    ])('restores %s from the URL into logic state', async (_name, searchParams, read, expected) => {
        router.actions.push('/web', searchParams)
        await expectLogic(logic).toFinishAllListeners()
        expect(read()).toEqual(expected)
    })

    it('restores an action conversion goal and couples the graphs tab to conversions', async () => {
        router.actions.push('/web', { 'conversionGoal.actionId': '42' })
        await expectLogic(logic).toFinishAllListeners()

        expect(logic.values.conversionGoal).toEqual({ actionId: 42 })
        // Restoring a conversion goal must drag the graphs tab onto conversions — the same coupling the
        // setConversionGoal reducer applies for a user-set goal.
        expect(logic.values._graphsTab).toBe(GraphsTab.UNIQUE_CONVERSIONS)
    })

    it('reconciles the URL when a restored param is normalised away', async () => {
        // A conversion goal makes PAGE_VIEWS an incompatible graphs tab, so restoration coerces it to
        // UNIQUE_USERS. The URL must be updated to match, or the visible chart and the shareable/reload
        // URL diverge (the per-action actionToUrl writes are suppressed during restore).
        router.actions.push('/web', { 'conversionGoal.actionId': '42', graphs_tab: 'PAGE_VIEWS' })
        await expectLogic(logic).toFinishAllListeners()

        expect(logic.values.graphsTab).toBe(GraphsTab.UNIQUE_USERS)
        expect(router.values.searchParams.graphs_tab).toBe(GraphsTab.UNIQUE_USERS)
    })

    it('restores the date range and interval from the URL', async () => {
        router.actions.push('/web', { date_from: '-30d', date_to: '-1d', interval: 'week' })
        await expectLogic(logic).toFinishAllListeners()

        expect(logic.values.dateFilter).toMatchObject({ dateFrom: '-30d', dateTo: '-1d', interval: 'week' })
    })

    it.each<[string, Record<string, string>]>([
        ['tab params', { device_tab: 'BROWSER', source_tab: 'REFERRING_DOMAIN', path_tab: 'INITIAL_PATH' }],
        ['cross-logic filter params', { domain: 'example.com', device_type: 'Desktop', percentile: 'p99' }],
        ['mixed params', { device_tab: 'BROWSER', domain: 'example.com', include_host_path: 'true' }],
    ])('restores %s in a single router push, without the actionToUrl cascade', async (_name, searchParams) => {
        const pushSpy = jest.spyOn(router.actions, 'push')

        router.actions.push('/web', searchParams)
        await expectLogic(logic).toFinishAllListeners()

        // The only push is our own navigation; restoring state must not re-push the URL per param.
        expect(pushSpy).toHaveBeenCalledTimes(1)
    })

    it('redirects off the bots tab when the bot-analysis flag is disabled', async () => {
        router.actions.push('/web/bots')
        await expectLogic(logic).toFinishAllListeners()

        // The pathname is project-prefixed in tests (e.g. /project/997/web); assert we left the bots route.
        expect(router.values.location.pathname.endsWith('/web')).toBe(true)
    })

    it('defaults the bots tab to the last day when the URL carries no date', async () => {
        featureFlagLogic.actions.setFeatureFlags([FEATURE_FLAGS.WEB_ANALYTICS_BOT_ANALYSIS], {
            [FEATURE_FLAGS.WEB_ANALYTICS_BOT_ANALYSIS]: true,
        })

        router.actions.push('/web/bots')
        await expectLogic(logic).toFinishAllListeners()

        expect(logic.values.productTab).toBe(ProductTab.BOT_ANALYTICS)
        expect(logic.values.dateFilter.dateFrom).toBe('-1d')
    })

    // kea-router parses search values, so booleans round-trip as booleans (include_host_path -> true).
    it.each<[string, () => void, string, unknown]>([
        ['setDeviceTab', () => logic.actions.setDeviceTab('BROWSER'), 'device_tab', 'BROWSER'],
        ['setSourceTab', () => logic.actions.setSourceTab('REFERRING_DOMAIN'), 'source_tab', 'REFERRING_DOMAIN'],
        ['setPathTab', () => logic.actions.setPathTab('INITIAL_PATH'), 'path_tab', 'INITIAL_PATH'],
        ['setGeographyTab', () => logic.actions.setGeographyTab('MAP'), 'geography_tab', 'MAP'],
        ['setIncludeHostPath', () => logic.actions.setIncludeHostPath(true), 'include_host_path', true],
    ])('mirrors %s back into the URL via actionToUrl', async (_name, act, key, expected) => {
        act()
        await expectLogic(logic).toFinishAllListeners()

        expect(router.values.searchParams[key]).toBe(expected)
    })

    const FILTER_A = {
        type: PropertyFilterType.Session as const,
        key: '$entry_utm_source',
        operator: PropertyOperator.Exact,
        value: ['google'],
    }
    const FILTER_B = {
        type: PropertyFilterType.Session as const,
        key: '$entry_utm_medium',
        operator: PropertyOperator.Exact,
        value: ['cpc'],
    }

    it('keeps all page performance controls in the shareable URL', async () => {
        featureFlagLogic.actions.setFeatureFlags([FEATURE_FLAGS.WEB_ANALYTICS_PAGE_PERFORMANCE], {
            [FEATURE_FLAGS.WEB_ANALYTICS_PAGE_PERFORMANCE]: true,
        })
        logic.actions.setProductTab(ProductTab.PAGE_PERFORMANCE)
        logic.actions.setDates('-30d', '2026-08-05')
        logic.actions.setConversionGoal({ actionId: 42 })
        logic.actions.setCompareFilter({ compare: true, compare_to: '-1y' })
        logic.actions.setIsPathCleaningEnabled(false)
        logic.actions.setShouldFilterTestAccounts(true)
        logic.actions.setWebAnalyticsFilters([FILTER_A])
        logic.actions.setDomainFilter('https://hedgebox.net')
        logic.actions.setDeviceTypeFilter('Desktop')
        // country and referrer fold into the page-performance queries too, so they must round-trip
        // through the URL or a shared link shows different numbers than the sender saw.
        logic.actions.setCountryFilter('US')
        logic.actions.setReferrerFilter('google.com')
        await expectLogic(logic).toFinishAllListeners()

        expect(router.values.location.pathname.endsWith('/web/page-performance')).toBe(true)
        expect(router.values.searchParams).toMatchObject({
            date_from: '-30d',
            date_to: '2026-08-05',
            'conversionGoal.actionId': 42,
            compare_filter: { compare: true, compare_to: '-1y' },
            path_cleaning: false,
            filter_test_accounts: true,
            filters: [FILTER_A],
            domain: 'https://hedgebox.net',
            device_type: 'Desktop',
            country: 'US',
            referrer: 'google.com',
        })
    })

    it("scrubs another tab's filters param when switching to the bots tab", async () => {
        featureFlagLogic.actions.setFeatureFlags([FEATURE_FLAGS.WEB_ANALYTICS_BOT_ANALYSIS], {
            [FEATURE_FLAGS.WEB_ANALYTICS_BOT_ANALYSIS]: true,
        })
        logic.actions.setWebAnalyticsFilters([FILTER_A])
        await expectLogic(logic).toFinishAllListeners()
        expect(router.values.searchParams['filters']).toEqual([FILTER_A])

        // The bots content (and so botAnalyticsLogic) has not mounted yet at serialization time.
        logic.actions.setProductTab(ProductTab.BOT_ANALYTICS)
        await expectLogic(logic).toFinishAllListeners()

        expect(router.values.location.pathname.endsWith('/web/bots')).toBe(true)
        expect(router.values.searchParams['filters']).toBeUndefined()
    })

    it('adopts a deep-linked filters param when the bots tab mounts', async () => {
        featureFlagLogic.actions.setFeatureFlags([FEATURE_FLAGS.WEB_ANALYTICS_BOT_ANALYSIS], {
            [FEATURE_FLAGS.WEB_ANALYTICS_BOT_ANALYSIS]: true,
        })
        router.actions.push('/web/bots', { filters: [FILTER_A] })
        await expectLogic(logic).toFinishAllListeners()

        const botLogic = botAnalyticsLogic()
        botLogic.mount()
        try {
            await expectLogic(botLogic).toFinishAllListeners()
            expect(botLogic.values.rawBotAnalyticsFilters).toEqual([FILTER_A])
            expect(router.values.searchParams['filters']).toEqual([FILTER_A])
        } finally {
            botLogic.unmount()
        }
    })

    it('writes persisted bot filters into the URL when the bots tab mounts', async () => {
        featureFlagLogic.actions.setFeatureFlags([FEATURE_FLAGS.WEB_ANALYTICS_BOT_ANALYSIS], {
            [FEATURE_FLAGS.WEB_ANALYTICS_BOT_ANALYSIS]: true,
        })
        router.actions.push('/web/bots')
        await expectLogic(logic).toFinishAllListeners()

        // First visit sets bot filters (persisted), then the user leaves the tab.
        const botLogic = botAnalyticsLogic()
        botLogic.mount()
        botLogic.actions.setBotAnalyticsFilters([FILTER_B])
        await expectLogic(botLogic).toFinishAllListeners()
        expect(router.values.searchParams['filters']).toEqual([FILTER_B])
        botLogic.unmount()

        // Returning through a bare URL: the mount serializes the persisted filters back.
        router.actions.push('/web/bots')
        await expectLogic(logic).toFinishAllListeners()
        expect(router.values.searchParams['filters']).toBeUndefined()

        const botLogicAgain = botAnalyticsLogic()
        botLogicAgain.mount()
        try {
            await expectLogic(botLogicAgain).toFinishAllListeners()
            expect(router.values.searchParams['filters']).toEqual([FILTER_B])
        } finally {
            botLogicAgain.unmount()
        }
    })

    it('applies property filters from a shared page performance URL', async () => {
        featureFlagLogic.actions.setFeatureFlags([FEATURE_FLAGS.WEB_ANALYTICS_PAGE_PERFORMANCE], {
            [FEATURE_FLAGS.WEB_ANALYTICS_PAGE_PERFORMANCE]: true,
        })

        router.actions.push('/web/page-performance', { filters: [FILTER_A] })
        await expectLogic(logic).toFinishAllListeners()

        expect(logic.values.productTab).toBe(ProductTab.PAGE_PERFORMANCE)
        expect(logic.values.rawWebAnalyticsFilters).toEqual([FILTER_A])
    })

    const enableBackNavReset = (): void => {
        featureFlagLogic.actions.setFeatureFlags([FEATURE_FLAGS.WEB_ANALYTICS_BACK_NAVIGATION_RESET], {
            [FEATURE_FLAGS.WEB_ANALYTICS_BACK_NAVIGATION_RESET]: true,
        })
    }

    it('clears a drilled-in filter when navigating back to a URL without filters (flag on)', async () => {
        enableBackNavReset()

        router.actions.push('/web', { filters: [FILTER_A] })
        await expectLogic(logic).toFinishAllListeners()
        expect(logic.values.rawWebAnalyticsFilters).toEqual([FILTER_A])

        router.actions.push('/web')
        await expectLogic(logic).toFinishAllListeners()
        expect(logic.values.rawWebAnalyticsFilters).toEqual([])
    })

    it('keeps the outer filter when stepping back between two drill levels (flag on)', async () => {
        enableBackNavReset()

        router.actions.push('/web', { filters: [FILTER_A, FILTER_B] })
        await expectLogic(logic).toFinishAllListeners()
        expect(logic.values.rawWebAnalyticsFilters).toEqual([FILTER_A, FILTER_B])

        router.actions.push('/web', { filters: [FILTER_A] })
        await expectLogic(logic).toFinishAllListeners()
        expect(logic.values.rawWebAnalyticsFilters).toEqual([FILTER_A])
    })

    it.each<[string, string, () => unknown]>([
        ['domain', 'example.com', () => logic.values.domainFilter],
        ['device_type', 'Desktop', () => logic.values.deviceTypeFilter],
        ['country', 'US', () => logic.values.countryFilter],
        ['referrer', 'google.com', () => logic.values.referrerFilter],
    ])(
        'clears a drilled-in %s filter when navigating back to a URL without it (flag on)',
        async (param, value, read) => {
            // These drill-downs fold into the query like `filters` do, so a back-navigation that
            // omits the param must clear the value — otherwise the shown data no longer matches the URL.
            featureFlagLogic.actions.setFeatureFlags(
                [FEATURE_FLAGS.WEB_ANALYTICS_BACK_NAVIGATION_RESET, FEATURE_FLAGS.WEB_ANALYTICS_PAGE_PERFORMANCE],
                {
                    [FEATURE_FLAGS.WEB_ANALYTICS_BACK_NAVIGATION_RESET]: true,
                    [FEATURE_FLAGS.WEB_ANALYTICS_PAGE_PERFORMANCE]: true,
                }
            )

            router.actions.push('/web/page-performance', { [param]: value })
            await expectLogic(logic).toFinishAllListeners()
            expect(read()).toBe(value)

            router.actions.push('/web/page-performance')
            await expectLogic(logic).toFinishAllListeners()
            expect(read()).toBeNull()
        }
    )

    it('leaves a drilled-in filter in place on back-navigation when the flag is off', async () => {
        router.actions.push('/web', { filters: [FILTER_A] })
        await expectLogic(logic).toFinishAllListeners()
        expect(logic.values.rawWebAnalyticsFilters).toEqual([FILTER_A])

        router.actions.push('/web')
        await expectLogic(logic).toFinishAllListeners()
        expect(logic.values.rawWebAnalyticsFilters).toEqual([FILTER_A])
    })

    it('keeps filters when moving to the Live tab, which never serializes them (flag on)', async () => {
        enableBackNavReset()

        router.actions.push('/web', { filters: [FILTER_A] })
        await expectLogic(logic).toFinishAllListeners()
        expect(logic.values.rawWebAnalyticsFilters).toEqual([FILTER_A])

        router.actions.push('/web/live')
        await expectLogic(logic).toFinishAllListeners()
        expect(logic.values.rawWebAnalyticsFilters).toEqual([FILTER_A])
    })

    it('keeps filters when a cold /web/bots load redirects to /web with the bots flag off (reset flag on)', async () => {
        enableBackNavReset()
        logic.actions.setWebAnalyticsFilters([FILTER_A])
        await expectLogic(logic).toFinishAllListeners()
        logic.cache.hasRestoredWebUrl = false

        router.actions.push('/web/bots')
        await expectLogic(logic).toFinishAllListeners()
        expect(logic.values.rawWebAnalyticsFilters).toEqual([FILTER_A])
    })
})
