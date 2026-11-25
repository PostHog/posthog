import { MOCK_DEFAULT_TEAM } from 'lib/api.mock'

import { router } from 'kea-router'
import { expectLogic } from 'kea-test-utils'
import { runInThisContext } from 'node:vm'

import { productSetupStatusLogic } from 'lib/components/ProductEmptyState/productSetupStatusLogic'
import { SetupTaskId, globalSetupLogic } from 'lib/components/ProductSetup'
import { FEATURE_FLAGS } from 'lib/constants'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { urls } from 'scenes/urls'

import { ProductKey } from '~/queries/schema/schema-general'
import { initKeaTests } from '~/test/init'
import { AnyPropertyFilter, PropertyFilterType, PropertyOperator } from '~/types'

import { aiObservabilitySharedLogic, buildApplyUrlStatePayload } from './aiObservabilitySharedLogic'
import { shellScopeLogic } from './redesign/shell/shellScopeLogic'
import { hasRecentAIEvents } from './utils/aiEvents'

jest.mock('lib/api')
jest.mock('./utils/aiEvents')

const mockHasRecentAIEvents = hasRecentAIEvents as jest.MockedFunction<typeof hasRecentAIEvents>

// Jest hands the test sandbox a copy of `process` whose `env` is a plain proxy, so assigning TZ
// there never reaches Node's timezone setter and the zone stays put. `runInThisContext` evaluates
// in the worker's own context, whose `process` is the real one.
function realProcessEnv(): NodeJS.ProcessEnv {
    return runInThisContext('process').env
}

function inBrowser<T>(timezone: string, now: string, run: () => T): T {
    const env = realProcessEnv()
    const previous = env.TZ
    env.TZ = timezone
    jest.useFakeTimers({ now: new Date(now) })
    try {
        return run()
    } finally {
        jest.useRealTimers()
        if (previous === undefined) {
            delete env.TZ
        } else {
            env.TZ = previous
        }
    }
}

describe('aiObservabilitySharedLogic', () => {
    describe('buildApplyUrlStatePayload', () => {
        const currentDateFilter = { dateFrom: '-1h', dateTo: null as string | null }
        const currentPropertyFilters: AnyPropertyFilter[] = []

        it.each([
            { desc: 'dateFrom differs', dateFrom: '-7d', dateTo: null as string | null, expected: true },
            { desc: 'dateTo differs', dateFrom: '-1h', dateTo: '2026-04-01', expected: true },
            { desc: 'both match current', dateFrom: '-1h', dateTo: null as string | null, expected: false },
        ])('flags datesChanged=$expected when $desc', ({ dateFrom, dateTo, expected }) => {
            const payload = buildApplyUrlStatePayload({
                dateFrom,
                dateTo,
                shouldFilterTestAccounts: false,
                propertyFilters: [],
                currentDateFilter,
                currentPropertyFilters,
            })
            expect(payload.datesChanged).toBe(expected)
        })

        const modelFilter: AnyPropertyFilter = {
            type: PropertyFilterType.Event,
            key: '$ai_model',
            operator: PropertyOperator.Exact,
            value: ['gpt-4o'],
        }
        it.each([
            {
                desc: 'contents equal — returns current reference',
                current: [modelFilter],
                next: [{ ...modelFilter }],
                expectCurrentRef: true,
            },
            {
                desc: 'contents differ — returns next reference',
                current: [] as AnyPropertyFilter[],
                next: [modelFilter],
                expectCurrentRef: false,
            },
        ])('propertyFilters: $desc', ({ current, next, expectCurrentRef }) => {
            const payload = buildApplyUrlStatePayload({
                dateFrom: '-1h',
                dateTo: null,
                shouldFilterTestAccounts: false,
                propertyFilters: next,
                currentDateFilter,
                currentPropertyFilters: current,
            })
            expect(payload.propertyFilters).toBe(expectCurrentRef ? current : next)
        })

        it('passes through shouldFilterTestAccounts and date values unchanged', () => {
            const payload = buildApplyUrlStatePayload({
                dateFrom: '-30d',
                dateTo: '-1d',
                shouldFilterTestAccounts: true,
                propertyFilters: [],
                currentDateFilter,
                currentPropertyFilters,
            })
            expect(payload.dateFrom).toBe('-30d')
            expect(payload.dateTo).toBe('-1d')
            expect(payload.shouldFilterTestAccounts).toBe(true)
        })
    })

    // A DataTable `person` cell mounts this logic on any scene, so a URL write on mount lands there.
    describe('test-account default and the URL', () => {
        beforeEach(() => {
            jest.clearAllMocks()
            mockHasRecentAIEvents.mockResolvedValue(false)
            initKeaTests(true, { ...MOCK_DEFAULT_TEAM, test_account_filters_default_checked: true })
        })

        it("leaves another scene's URL alone when mounted there", async () => {
            const drillDown = { kind: 'DataTableNode', source: { kind: 'ActorsQuery', select: ['person'] } }
            router.actions.push(urls.insightNew({ query: drillDown as any }))
            const { pathname, search, hash } = router.values.location

            const logic = aiObservabilitySharedLogic()
            logic.mount()
            await expectLogic(logic).toFinishAllListeners()

            expect(logic.values.shouldFilterTestAccounts).toBe(false)
            expect(router.values.location).toMatchObject({ pathname, search, hash })
        })

        it('applies the default on its own route without dropping the hash', async () => {
            router.actions.push(urls.aiObservabilityTraces(), {}, { panel: 'max' })

            const logic = aiObservabilitySharedLogic()
            logic.mount()
            await expectLogic(logic).toFinishAllListeners()

            expect(logic.values.shouldFilterTestAccounts).toBe(true)
            expect(router.values.searchParams.filter_test_accounts).toBe(true)
            expect(router.values.hashParams.panel).toBe('max')
        })
    })

    // The traces list reads and writes its own filters and dates there.
    describe('the traces path with the navigation flag on', () => {
        const NAV = FEATURE_FLAGS.AI_OBSERVABILITY_NAV_REDESIGN

        function mountWithFlags(flags: string[]): ReturnType<typeof aiObservabilitySharedLogic.build> {
            featureFlagLogic.mount()
            featureFlagLogic.actions.setFeatureFlags(flags, Object.fromEntries(flags.map((flag) => [flag, true])))
            const logic = aiObservabilitySharedLogic()
            logic.mount()
            return logic
        }

        beforeEach(() => {
            // A choice that differs from the project's default is remembered in local storage across tests.
            localStorage.clear()
            jest.clearAllMocks()
            mockHasRecentAIEvents.mockResolvedValue(false)
            initKeaTests(true, { ...MOCK_DEFAULT_TEAM, test_account_filters_default_checked: true })
        })

        it.each([
            ['leaves its range alone on the traces path with the flag on', [NAV], urls.aiObservabilityTraces(), false],
            ['follows the traces path with the flag off', [], urls.aiObservabilityTraces(), true],
            ['follows the sessions path with the flag on', [NAV], urls.aiObservabilitySessions(), true],
        ])('%s', async (_name, flags, path, follows) => {
            const logic = mountWithFlags(flags)
            const { dateFrom } = logic.values.dateFilter

            router.actions.push(path, { date_from: '-30d' })
            await expectLogic(logic).toFinishAllListeners()

            expect(logic.values.dateFilter.dateFrom).toBe(follows ? '-30d' : dateFrom)
        })

        it.each([
            ['the nav flag is on', [NAV], false],
            ['the flag is off', [], true],
        ])('follows the dashboard path when %s', async (_name, flags, follows) => {
            const logic = mountWithFlags(flags)
            const { dateFrom } = logic.values.dashboardDateFilter

            router.actions.push(urls.aiObservabilityDashboard(), { date_from: '-30d' })
            await expectLogic(logic).toFinishAllListeners()

            expect(logic.values.dashboardDateFilter.dateFrom).toBe(follows ? '-30d' : dateFrom)
        })

        it('does not rewrite the URL on the dashboard path when the nav flag is on', async () => {
            router.actions.push(urls.aiObservabilityDashboard(), { date_from: '-24h' })
            const logic = mountWithFlags([NAV])

            logic.actions.setDashboardDates('-30d', null)
            logic.actions.setShouldFilterTestAccounts(true)
            await expectLogic(logic).toFinishAllListeners()

            expect(router.values.searchParams).toEqual({ date_from: '-24h' })
        })

        it('keeps an explicit test account choice of false when it syncs the range on another path', async () => {
            const logic = mountWithFlags([NAV])

            router.actions.push(`${urls.aiObservabilitySessions()}?date_from=-30d&filter_test_accounts=false`)
            await expectLogic(logic).toFinishAllListeners()

            expect(logic.values.shouldFilterTestAccounts).toBe(false)
            expect(router.values.location.search).toContain('filter_test_accounts=false')
        })

        it('hands a test account choice of false made on the sessions path to the shell', async () => {
            router.actions.push(urls.aiObservabilityTraces())
            shellScopeLogic.mount()
            shellScopeLogic.actions.setFilterTestAccounts(true)
            const logic = mountWithFlags([NAV])
            router.actions.push(urls.aiObservabilitySessions(), router.values.searchParams)
            await expectLogic(logic).toFinishAllListeners()
            expect(logic.values.shouldFilterTestAccounts).toBe(true)

            logic.actions.setShouldFilterTestAccounts(false)
            await expectLogic(logic).toFinishAllListeners()

            expect(shellScopeLogic.values.filterTestAccounts).toBe(false)
        })

        it('writes nothing to the traces URL', async () => {
            router.actions.push(urls.aiObservabilityTraces(), { view: 'errors' })
            const logic = mountWithFlags([NAV])

            logic.actions.setDates('-30d', null)
            logic.actions.setSearchQuery('refund')
            await expectLogic(logic).toFinishAllListeners()

            expect(router.values.searchParams).toEqual({ view: 'errors' })
        })

        it("applies the project's test account default on the next path after entering traces first", async () => {
            router.actions.push(urls.aiObservabilityTraces())
            const logic = mountWithFlags([NAV])
            await expectLogic(logic).toFinishAllListeners()
            expect(logic.values.shouldFilterTestAccounts).toBe(false)

            router.actions.push(urls.aiObservabilitySessions())
            await expectLogic(logic).toFinishAllListeners()

            expect(logic.values.shouldFilterTestAccounts).toBe(true)
            expect(router.values.searchParams.filter_test_accounts).toBe(true)
        })

        it.each([
            ['traces', urls.aiObservabilityTraces()],
            ['dashboard', urls.aiObservabilityDashboard()],
        ])('still marks the cost tracking setup task done on the %s path', async (_name, path) => {
            globalSetupLogic.mount()
            router.actions.push(path)

            await expectLogic(globalSetupLogic, () => {
                mountWithFlags([NAV])
            }).toDispatchActions([globalSetupLogic.actionCreators.markTaskAsCompleted(SetupTaskId.TrackCosts)])
        })
    })

    // Guards the connect + mapping into the app-wide setup-status layer: if either
    // breaks, the scene empty-state gate strands users on its spinner, or shows the
    // setup screen to teams that already have AI events.
    describe('setup status detection', () => {
        beforeEach(() => {
            jest.clearAllMocks()
            initKeaTests()
        })

        it.each([
            [true, 'has-data'],
            [false, 'needs-setup'],
            [null, 'unknown'],
        ])('pushes hasSentAiEvent=%s into productSetupStatusLogic as %s', async (hasEvents, expected) => {
            mockHasRecentAIEvents.mockResolvedValue(hasEvents)
            const logic = aiObservabilitySharedLogic()
            logic.mount()
            await expectLogic(logic).toFinishAllListeners()
            expect(productSetupStatusLogic({ productKey: ProductKey.AI_OBSERVABILITY }).values.status).toBe(expected)
        })

        // Guards the fail-open path: a persistently failing detection query must
        // publish `unknown` (gate renders the scene), not leave the gate on its
        // spinner forever.
        it('publishes unknown when detection fails before any answer exists', async () => {
            mockHasRecentAIEvents.mockRejectedValue(new Error('query failed'))
            const logic = aiObservabilitySharedLogic()
            logic.mount()
            await expectLogic(logic).toFinishAllListeners()
            expect(productSetupStatusLogic({ productKey: ProductKey.AI_OBSERVABILITY }).values.status).toBe('unknown')
        })

        it.each([
            ['rejects', (): void => void mockHasRecentAIEvents.mockRejectedValue(new Error('query failed'))],
            ['cannot answer', (): void => void mockHasRecentAIEvents.mockResolvedValue(null)],
        ])('a re-check that %s never downgrades an existing answer', async (_, breakTheCheck) => {
            mockHasRecentAIEvents.mockResolvedValue(true)
            const logic = aiObservabilitySharedLogic()
            logic.mount()
            await expectLogic(logic).toFinishAllListeners()
            breakTheCheck()
            logic.actions.loadAIEventDefinition()
            await expectLogic(logic).toFinishAllListeners()
            expect(productSetupStatusLogic({ productKey: ProductKey.AI_OBSERVABILITY }).values.status).toBe('has-data')
        })

        it('doubles the re-check delay while the check cannot answer, and restores it once it can', async () => {
            mockHasRecentAIEvents.mockResolvedValue(null)
            jest.useFakeTimers()
            try {
                const logic = aiObservabilitySharedLogic()
                logic.mount()
                // `toFinishAllListeners` waits on a real timer, so it never settles here.
                await jest.advanceTimersByTimeAsync(0)
                expect(mockHasRecentAIEvents).toHaveBeenCalledTimes(1)

                await jest.advanceTimersByTimeAsync(20000)
                expect(mockHasRecentAIEvents).toHaveBeenCalledTimes(1)
                await jest.advanceTimersByTimeAsync(20000)
                expect(mockHasRecentAIEvents).toHaveBeenCalledTimes(2)

                mockHasRecentAIEvents.mockResolvedValue(false)
                await jest.advanceTimersByTimeAsync(80000)
                expect(mockHasRecentAIEvents).toHaveBeenCalledTimes(3)

                await jest.advanceTimersByTimeAsync(20000)
                expect(mockHasRecentAIEvents).toHaveBeenCalledTimes(4)
            } finally {
                jest.useRealTimers()
            }
        })
    })

    describe('instrumentationVerdictApplies', () => {
        beforeEach(() => {
            jest.clearAllMocks()
            mockHasRecentAIEvents.mockResolvedValue(true)
            // `dateFilter` persists, so a range set by one case would otherwise be the next one's default.
            localStorage.clear()
            initKeaTests()
        })

        // The range and the window it is measured against both resolve in UTC, so the answer must
        // not move with the browser. Each clock below sits on a different calendar date locally
        // than in UTC, which is where an anchor read from the browser's own zone drifts a day and
        // silently drops the instrumentation empty state.
        it.each([
            ['Asia/Tokyo', '2026-08-25T18:00:00.000Z'],
            ['America/Los_Angeles', '2026-08-25T02:00:00.000Z'],
        ])('covers a range of exactly the checklist window in %s', (timezone, now) => {
            const logic = aiObservabilitySharedLogic()
            logic.mount()
            logic.actions.setDates('-30d', null)

            expect(inBrowser(timezone, now, () => logic.values.instrumentationVerdictApplies(30))).toBe(true)
        })
    })
})
