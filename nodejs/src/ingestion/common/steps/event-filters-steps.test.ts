import { createTestEventHeaders } from '../../../../tests/helpers/event-headers'
import { getMetricValues, resetMetrics } from '../../../../tests/helpers/metrics'
import { createTestTeam } from '../../../../tests/helpers/team'
import { IngestionOutputs } from '../../outputs/ingestion-outputs'
import { isDropResult, isOkResult, ok } from '../../pipelines/results'
import { EventFilterManager } from '../event-filters'
import { EventFiltersBatchAppMetrics } from '../event-filters/batch-app-metrics'
import { FilterNode } from '../event-filters/schema'
import { and, cond, not, or } from '../event-filters/test-helpers'
import { AppMetricsOutput } from '../outputs'
import {
    createApplyEventFiltersStep,
    createEventFiltersBatchAppMetricsBeforeBatchStep,
    createFlushEventFiltersBatchAppMetricsStep,
} from './event-filters-steps'

const mockOutputs = {
    queueMessages: jest.fn().mockResolvedValue(undefined),
} as unknown as jest.Mocked<Pick<IngestionOutputs<AppMetricsOutput>, 'queueMessages'>> &
    IngestionOutputs<AppMetricsOutput>

function makePipelineContext(extra: Record<string, unknown> = {}) {
    return { sideEffects: [], warnings: [], ...extra }
}

describe('createEventFiltersBatchAppMetricsBeforeBatchStep', () => {
    beforeEach(() => {
        jest.clearAllMocks()
    })

    it('creates a batch metrics instance in the batch context', async () => {
        const step = createEventFiltersBatchAppMetricsBeforeBatchStep(mockOutputs)
        const result = await step({
            elements: [{ result: ok({ foo: 1 }), context: makePipelineContext() }],
            batchId: 0,
        })

        expect(isOkResult(result)).toBe(true)
        if (!isOkResult(result)) {
            return
        }
        expect(result.value.batchContext.eventFiltersBatchAppMetrics).toBeInstanceOf(EventFiltersBatchAppMetrics)
    })

    it('attaches the same batch metrics instance to each element', async () => {
        const step = createEventFiltersBatchAppMetricsBeforeBatchStep(mockOutputs)
        const result = await step({
            elements: [
                { result: ok({ a: 1 }), context: makePipelineContext() },
                { result: ok({ a: 2 }), context: makePipelineContext() },
            ],
            batchId: 0,
        })

        expect(isOkResult(result)).toBe(true)
        if (!isOkResult(result)) {
            return
        }

        const batchMetrics = result.value.batchContext.eventFiltersBatchAppMetrics
        for (const element of result.value.elements) {
            expect(element.result.value.eventFiltersBatchAppMetrics).toBe(batchMetrics)
        }
    })

    it('preserves existing element values and context', async () => {
        const step = createEventFiltersBatchAppMetricsBeforeBatchStep(mockOutputs)
        const result = await step({
            elements: [{ result: ok({ data: 'hello' }), context: makePipelineContext({ ctx: true }) }],
            batchId: 0,
        })

        expect(isOkResult(result)).toBe(true)
        if (!isOkResult(result)) {
            return
        }
        expect((result.value.elements[0].result.value as any).data).toBe('hello')
        expect((result.value.elements[0].context as any).ctx).toBe(true)
    })
})

describe('createApplyEventFiltersStep', () => {
    const mockManager = {
        getFilter: jest.fn(),
    } as unknown as jest.Mocked<Pick<EventFilterManager, 'getFilter'>> & EventFilterManager

    beforeEach(() => {
        jest.clearAllMocks()
        resetMetrics()
    })

    it('passes through when no filter exists for the team', async () => {
        mockManager.getFilter.mockReturnValue(null)
        const metrics = new EventFiltersBatchAppMetrics(mockOutputs)
        const step = createApplyEventFiltersStep(mockManager)
        const input = {
            team: createTestTeam({ id: 1 }),
            headers: createTestEventHeaders({ event: '$pageview' }),
            eventFiltersBatchAppMetrics: metrics,
        }

        const result = await step(input)

        expect(isOkResult(result)).toBe(true)
    })

    it('drops event and increments metric in live mode', async () => {
        mockManager.getFilter.mockReturnValue({
            id: 'f1',
            team_id: 1,
            mode: 'live',
            filter_tree: cond('event_name', 'exact', '$internal'),
        })
        const metrics = new EventFiltersBatchAppMetrics(mockOutputs)
        const incrementSpy = jest.spyOn(metrics, 'increment')
        const step = createApplyEventFiltersStep(mockManager)
        const input = {
            team: createTestTeam({ id: 1 }),
            headers: createTestEventHeaders({ event: '$internal' }),
            eventFiltersBatchAppMetrics: metrics,
        }

        const result = await step(input)

        expect(isDropResult(result)).toBe(true)
        expect(incrementSpy).toHaveBeenCalledWith(1, 'f1', 'dropped')
    })

    it('passes through and increments would_be_dropped in dry_run mode', async () => {
        mockManager.getFilter.mockReturnValue({
            id: 'f1',
            team_id: 1,
            mode: 'dry_run',
            filter_tree: cond('event_name', 'exact', '$internal'),
        })
        const metrics = new EventFiltersBatchAppMetrics(mockOutputs)
        const incrementSpy = jest.spyOn(metrics, 'increment')
        const step = createApplyEventFiltersStep(mockManager)
        const input = {
            team: createTestTeam({ id: 1 }),
            headers: createTestEventHeaders({ event: '$internal' }),
            eventFiltersBatchAppMetrics: metrics,
        }

        const result = await step(input)

        expect(isOkResult(result)).toBe(true)
        expect(incrementSpy).toHaveBeenCalledWith(1, 'f1', 'would_be_dropped')
    })

    it('does not increment metrics when filter does not match', async () => {
        mockManager.getFilter.mockReturnValue({
            id: 'f1',
            team_id: 1,
            mode: 'live',
            filter_tree: cond('event_name', 'exact', '$internal'),
        })
        const metrics = new EventFiltersBatchAppMetrics(mockOutputs)
        const incrementSpy = jest.spyOn(metrics, 'increment')
        const step = createApplyEventFiltersStep(mockManager)
        const input = {
            team: createTestTeam({ id: 1 }),
            headers: createTestEventHeaders({ event: '$pageview' }),
            eventFiltersBatchAppMetrics: metrics,
        }

        await step(input)

        expect(incrementSpy).not.toHaveBeenCalled()
    })

    it('increments dropped prometheus metric in live mode', async () => {
        mockManager.getFilter.mockReturnValue({
            id: 'f1',
            team_id: 1,
            mode: 'live',
            filter_tree: cond('event_name', 'exact', '$internal'),
        })
        const metrics = new EventFiltersBatchAppMetrics(mockOutputs)
        const step = createApplyEventFiltersStep(mockManager)

        await step({
            team: createTestTeam({ id: 1 }),
            headers: createTestEventHeaders({ event: '$internal' }),
            eventFiltersBatchAppMetrics: metrics,
        })

        const values = await getMetricValues('ingestion_filters_events_evaluated')
        expect(values).toEqual([{ labels: { outcome: 'dropped' }, value: 1 }])
    })

    it('increments shadow_dropped prometheus metric in dry_run mode', async () => {
        mockManager.getFilter.mockReturnValue({
            id: 'f1',
            team_id: 1,
            mode: 'dry_run',
            filter_tree: cond('event_name', 'exact', '$internal'),
        })
        const metrics = new EventFiltersBatchAppMetrics(mockOutputs)
        const step = createApplyEventFiltersStep(mockManager)

        await step({
            team: createTestTeam({ id: 1 }),
            headers: createTestEventHeaders({ event: '$internal' }),
            eventFiltersBatchAppMetrics: metrics,
        })

        const values = await getMetricValues('ingestion_filters_events_evaluated')
        expect(values).toEqual([{ labels: { outcome: 'shadow_dropped' }, value: 1 }])
    })

    it('increments ingested prometheus metric when filter does not match', async () => {
        mockManager.getFilter.mockReturnValue({
            id: 'f1',
            team_id: 1,
            mode: 'live',
            filter_tree: cond('event_name', 'exact', '$internal'),
        })
        const metrics = new EventFiltersBatchAppMetrics(mockOutputs)
        const step = createApplyEventFiltersStep(mockManager)

        await step({
            team: createTestTeam({ id: 1 }),
            headers: createTestEventHeaders({ event: '$pageview' }),
            eventFiltersBatchAppMetrics: metrics,
        })

        const values = await getMetricValues('ingestion_filters_events_evaluated')
        expect(values).toEqual([{ labels: { outcome: 'ingested' }, value: 1 }])
    })

    it('does not increment prometheus metric when no filter exists', async () => {
        mockManager.getFilter.mockReturnValue(null)
        const metrics = new EventFiltersBatchAppMetrics(mockOutputs)
        const step = createApplyEventFiltersStep(mockManager)

        await step({
            team: createTestTeam({ id: 1 }),
            headers: createTestEventHeaders({ event: '$pageview' }),
            eventFiltersBatchAppMetrics: metrics,
        })

        const values = await getMetricValues('ingestion_filters_events_evaluated')
        expect(values).toEqual([])
    })

    // Mirrors Python test_complex_tree_with_many_test_cases:
    // Drop if: (event is "$autocapture" OR event contains "bot_")
    //          AND NOT (distinct_id is "admin-user")
    const complexTree = and(
        or(cond('event_name', 'exact', '$autocapture'), cond('event_name', 'contains', 'bot_')),
        not(cond('distinct_id', 'exact', 'admin-user'))
    )

    interface FilterScenario {
        name: string
        filter: FilterNode
        event: { event_name?: string; distinct_id?: string }
        drops: boolean
    }

    const scenarios: FilterScenario[] = [
        // condition matching
        {
            name: 'exact event_name match',
            filter: cond('event_name', 'exact', '$pageview'),
            event: { event_name: '$pageview' },
            drops: true,
        },
        {
            name: 'exact event_name no match',
            filter: cond('event_name', 'exact', '$pageview'),
            event: { event_name: '$click' },
            drops: false,
        },
        {
            name: 'exact distinct_id match',
            filter: cond('distinct_id', 'exact', 'bot-1'),
            event: { distinct_id: 'bot-1' },
            drops: true,
        },
        {
            name: 'exact distinct_id no match',
            filter: cond('distinct_id', 'exact', 'bot-1'),
            event: { distinct_id: 'user-1' },
            drops: false,
        },
        {
            name: 'contains match',
            filter: cond('distinct_id', 'contains', 'bot-'),
            event: { distinct_id: 'bot-crawler' },
            drops: true,
        },
        {
            name: 'contains no match',
            filter: cond('distinct_id', 'contains', 'bot-'),
            event: { distinct_id: 'real-user' },
            drops: false,
        },
        {
            name: 'missing field',
            filter: cond('distinct_id', 'exact', 'test'),
            event: { event_name: '$pageview' },
            drops: false,
        },
        { name: 'undefined field', filter: cond('event_name', 'exact', 'test'), event: {}, drops: false },

        // empty groups are conservative (never drop)
        { name: 'empty AND', filter: { type: 'and', children: [] }, event: { event_name: '$pageview' }, drops: false },
        { name: 'empty OR', filter: { type: 'or', children: [] }, event: { event_name: '$pageview' }, drops: false },
        {
            name: 'NOT(empty AND) drops',
            filter: not({ type: 'and', children: [] }),
            event: { event_name: 'x' },
            drops: true,
        },
        {
            name: 'NOT(empty OR) drops',
            filter: not({ type: 'or', children: [] }),
            event: { event_name: 'x' },
            drops: true,
        },
        {
            name: 'AND of empty groups',
            filter: and({ type: 'or', children: [] }, { type: 'or', children: [] }),
            event: { event_name: '$pageview' },
            drops: false,
        },

        // boolean logic
        {
            name: 'AND all match',
            filter: and(cond('event_name', 'exact', '$internal'), cond('distinct_id', 'contains', 'bot-')),
            event: { event_name: '$internal', distinct_id: 'bot-x' },
            drops: true,
        },
        {
            name: 'AND one misses',
            filter: and(cond('event_name', 'exact', '$internal'), cond('distinct_id', 'contains', 'bot-')),
            event: { event_name: '$internal', distinct_id: 'user' },
            drops: false,
        },
        {
            name: 'OR first matches',
            filter: or(cond('event_name', 'exact', 'a'), cond('event_name', 'exact', 'b')),
            event: { event_name: 'a' },
            drops: true,
        },
        {
            name: 'OR second matches',
            filter: or(cond('event_name', 'exact', 'a'), cond('event_name', 'exact', 'b')),
            event: { event_name: 'b' },
            drops: true,
        },
        {
            name: 'OR none match',
            filter: or(cond('event_name', 'exact', 'a'), cond('event_name', 'exact', 'b')),
            event: { event_name: 'c' },
            drops: false,
        },
        {
            name: 'NOT inverts match',
            filter: not(cond('event_name', 'exact', 'keep')),
            event: { event_name: 'keep' },
            drops: false,
        },
        {
            name: 'NOT inverts miss',
            filter: not(cond('event_name', 'exact', 'keep')),
            event: { event_name: 'other' },
            drops: true,
        },

        // complex: OR of AND groups
        {
            name: 'OR(cond, AND) first matches',
            filter: or(
                cond('event_name', 'exact', '$drop_me'),
                and(cond('event_name', 'exact', '$internal'), cond('distinct_id', 'contains', 'bot-'))
            ),
            event: { event_name: '$drop_me', distinct_id: 'anyone' },
            drops: true,
        },
        {
            name: 'OR(cond, AND) AND matches',
            filter: or(
                cond('event_name', 'exact', '$drop_me'),
                and(cond('event_name', 'exact', '$internal'), cond('distinct_id', 'contains', 'bot-'))
            ),
            event: { event_name: '$internal', distinct_id: 'bot-x' },
            drops: true,
        },
        {
            name: 'OR(cond, AND) neither matches',
            filter: or(
                cond('event_name', 'exact', '$drop_me'),
                and(cond('event_name', 'exact', '$internal'), cond('distinct_id', 'contains', 'bot-'))
            ),
            event: { event_name: '$internal', distinct_id: 'user' },
            drops: false,
        },

        // complex: NOT wrapping OR (allowlist pattern)
        {
            name: 'NOT(OR) allowlist — allowed event passes',
            filter: not(or(cond('event_name', 'exact', 'allowed_1'), cond('event_name', 'exact', 'allowed_2'))),
            event: { event_name: 'allowed_1' },
            drops: false,
        },
        {
            name: 'NOT(OR) allowlist — other event drops',
            filter: not(or(cond('event_name', 'exact', 'allowed_1'), cond('event_name', 'exact', 'allowed_2'))),
            event: { event_name: 'other' },
            drops: true,
        },

        // complex: AND + OR + NOT (mirrors Python test_complex_tree_with_many_test_cases)
        {
            name: 'complex: $autocapture from regular user drops',
            filter: complexTree,
            event: { event_name: '$autocapture', distinct_id: 'user-1' },
            drops: true,
        },
        {
            name: 'complex: bot_ from regular user drops',
            filter: complexTree,
            event: { event_name: 'bot_heartbeat', distinct_id: 'user-2' },
            drops: true,
        },
        {
            name: 'complex: $autocapture from admin passes (NOT protects)',
            filter: complexTree,
            event: { event_name: '$autocapture', distinct_id: 'admin-user' },
            drops: false,
        },
        {
            name: 'complex: bot_ from admin passes',
            filter: complexTree,
            event: { event_name: 'bot_ping', distinct_id: 'admin-user' },
            drops: false,
        },
        {
            name: 'complex: normal event passes',
            filter: complexTree,
            event: { event_name: 'purchase', distinct_id: 'user-1' },
            drops: false,
        },
        {
            name: 'complex: partial bot_ match drops',
            filter: complexTree,
            event: { event_name: 'internal_bot_check', distinct_id: 'service-1' },
            drops: true,
        },
        {
            name: 'complex: missing event_name passes',
            filter: complexTree,
            event: { distinct_id: 'user-1' },
            drops: false,
        },
        {
            name: 'complex: missing distinct_id drops',
            filter: complexTree,
            event: { event_name: '$autocapture' },
            drops: true,
        },
    ]

    it.each(scenarios)('$name', async ({ filter, event, drops }) => {
        mockManager.getFilter.mockReturnValue({
            id: 'test-filter',
            team_id: 1,
            mode: 'live',
            filter_tree: filter,
        })
        const metrics = new EventFiltersBatchAppMetrics(mockOutputs)
        const step = createApplyEventFiltersStep(mockManager)
        const input = {
            team: createTestTeam({ id: 1 }),
            headers: createTestEventHeaders({ event: event.event_name, distinct_id: event.distinct_id }),
            eventFiltersBatchAppMetrics: metrics,
        }

        const result = await step(input)

        if (drops) {
            expect(isDropResult(result)).toBe(true)
        } else {
            expect(isOkResult(result)).toBe(true)
        }
    })
})

describe('createFlushEventFiltersBatchAppMetricsStep', () => {
    beforeEach(() => {
        jest.clearAllMocks()
    })

    it('flushes batch metrics and returns flush as a side effect', async () => {
        const metrics = new EventFiltersBatchAppMetrics(mockOutputs)
        metrics.increment(1, 'f1', 'dropped')
        metrics.increment(1, 'f1', 'dropped')

        const step = createFlushEventFiltersBatchAppMetricsStep()
        const input = {
            elements: [],
            batchContext: { eventFiltersBatchAppMetrics: metrics },
        }

        const result = await step(input)

        expect(isOkResult(result)).toBe(true)
        if (!isOkResult(result)) {
            return
        }
        expect(result.sideEffects).toHaveLength(1)

        await Promise.all(result.sideEffects)
        expect(mockOutputs.queueMessages).toHaveBeenCalledTimes(1)
    })

    it('returns flush side effect even when no metrics were recorded', async () => {
        const metrics = new EventFiltersBatchAppMetrics(mockOutputs)

        const step = createFlushEventFiltersBatchAppMetricsStep()
        const input = {
            elements: [],
            batchContext: { eventFiltersBatchAppMetrics: metrics },
        }

        const result = await step(input)

        expect(isOkResult(result)).toBe(true)
        if (!isOkResult(result)) {
            return
        }
        expect(result.sideEffects).toHaveLength(1)

        await Promise.all(result.sideEffects)
        expect(mockOutputs.queueMessages).not.toHaveBeenCalled()
    })

    it('preserves input in the result', async () => {
        const metrics = new EventFiltersBatchAppMetrics(mockOutputs)

        const step = createFlushEventFiltersBatchAppMetricsStep()
        const input = {
            elements: [{ some: 'data' }],
            batchContext: { eventFiltersBatchAppMetrics: metrics },
        }

        const result = await step(input)

        expect(isOkResult(result)).toBe(true)
        if (!isOkResult(result)) {
            return
        }
        expect(result.value).toBe(input)
    })
})
