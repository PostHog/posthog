import { expectLogic } from 'kea-test-utils'
import { runInThisContext } from 'node:vm'

import { productSetupStatusLogic } from 'lib/components/ProductEmptyState/productSetupStatusLogic'

import { ProductKey } from '~/queries/schema/schema-general'
import { initKeaTests } from '~/test/init'
import { AnyPropertyFilter, PropertyFilterType, PropertyOperator } from '~/types'

import { aiObservabilitySharedLogic, buildApplyUrlStatePayload } from './aiObservabilitySharedLogic'
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

        it('a failing re-check never downgrades an existing answer', async () => {
            mockHasRecentAIEvents.mockResolvedValue(true)
            const logic = aiObservabilitySharedLogic()
            logic.mount()
            await expectLogic(logic).toFinishAllListeners()
            mockHasRecentAIEvents.mockRejectedValue(new Error('query failed'))
            logic.actions.loadAIEventDefinition()
            await expectLogic(logic).toFinishAllListeners()
            expect(productSetupStatusLogic({ productKey: ProductKey.AI_OBSERVABILITY }).values.status).toBe('has-data')
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
