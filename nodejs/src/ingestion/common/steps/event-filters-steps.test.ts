import { PipelineEvent, Team } from '../../../types'
import { IngestionOutputs } from '../../outputs/ingestion-outputs'
import { PipelineContext } from '../../pipelines/pipeline.interface'
import { isDropResult, isOkResult, ok } from '../../pipelines/results'
import { EventFilterManager } from '../event-filters'
import { EventFiltersBatchAppMetrics } from '../event-filters/batch-app-metrics'
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

function makeContext<C>(extra?: C): PipelineContext<C> {
    return { ...extra, sideEffects: [], warnings: [] } as PipelineContext<C>
}

function makeTeam(id: number): Team {
    return { id } as Team
}

function makeEvent(event: string, distinct_id?: string): PipelineEvent {
    return { event, distinct_id } as PipelineEvent
}

function makeInput(teamId: number, eventName: string, batchMetrics: EventFiltersBatchAppMetrics, distinct_id?: string) {
    return {
        event: makeEvent(eventName, distinct_id),
        team: makeTeam(teamId),
        headers: { token: 'tok', distinct_id } as any,
        eventFiltersBatchAppMetrics: batchMetrics,
    }
}

describe('createEventFiltersBatchAppMetricsBeforeBatchStep', () => {
    beforeEach(() => {
        jest.clearAllMocks()
    })

    it('creates a batch metrics instance in the batch context', async () => {
        const step = createEventFiltersBatchAppMetricsBeforeBatchStep(mockOutputs)
        const result = await step({
            elements: [{ result: ok({ foo: 1 }), context: makeContext() }],
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
                { result: ok({ a: 1 }), context: makeContext() },
                { result: ok({ a: 2 }), context: makeContext() },
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
            elements: [{ result: ok({ data: 'hello' }), context: makeContext({ ctx: true }) }],
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
    const batchMetrics = new EventFiltersBatchAppMetrics(mockOutputs)

    const mockManager = {
        getFilter: jest.fn(),
    } as unknown as jest.Mocked<Pick<EventFilterManager, 'getFilter'>> & EventFilterManager

    beforeEach(() => {
        jest.clearAllMocks()
    })

    it('passes through when no filter exists for the team', async () => {
        mockManager.getFilter.mockReturnValue(null)
        const step = createApplyEventFiltersStep(mockManager)
        const input = makeInput(1, '$pageview', batchMetrics)

        const result = await step(input)

        expect(isOkResult(result)).toBe(true)
    })

    it('passes through when filter does not match', async () => {
        mockManager.getFilter.mockReturnValue({
            id: 'f1',
            team_id: 1,
            mode: 'live',
            filter_tree: { type: 'condition', field: 'event_name', operator: 'exact', value: '$internal' },
        })
        const step = createApplyEventFiltersStep(mockManager)
        const input = makeInput(1, '$pageview', batchMetrics)

        const result = await step(input)

        expect(isOkResult(result)).toBe(true)
    })

    it('drops event and increments metric in live mode', async () => {
        mockManager.getFilter.mockReturnValue({
            id: 'f1',
            team_id: 1,
            mode: 'live',
            filter_tree: { type: 'condition', field: 'event_name', operator: 'exact', value: '$internal' },
        })
        const metrics = new EventFiltersBatchAppMetrics(mockOutputs)
        const incrementSpy = jest.spyOn(metrics, 'increment')
        const step = createApplyEventFiltersStep(mockManager)
        const input = makeInput(1, '$internal', metrics)

        const result = await step(input)

        expect(isDropResult(result)).toBe(true)
        expect(incrementSpy).toHaveBeenCalledWith(1, 'f1', 'dropped')
    })

    it('passes through and increments would_be_dropped in dry_run mode', async () => {
        mockManager.getFilter.mockReturnValue({
            id: 'f1',
            team_id: 1,
            mode: 'dry_run',
            filter_tree: { type: 'condition', field: 'event_name', operator: 'exact', value: '$internal' },
        })
        const metrics = new EventFiltersBatchAppMetrics(mockOutputs)
        const incrementSpy = jest.spyOn(metrics, 'increment')
        const step = createApplyEventFiltersStep(mockManager)
        const input = makeInput(1, '$internal', metrics)

        const result = await step(input)

        expect(isOkResult(result)).toBe(true)
        expect(incrementSpy).toHaveBeenCalledWith(1, 'f1', 'would_be_dropped')
    })

    it('does not increment metrics when filter does not match', async () => {
        mockManager.getFilter.mockReturnValue({
            id: 'f1',
            team_id: 1,
            mode: 'live',
            filter_tree: { type: 'condition', field: 'event_name', operator: 'exact', value: '$internal' },
        })
        const metrics = new EventFiltersBatchAppMetrics(mockOutputs)
        const incrementSpy = jest.spyOn(metrics, 'increment')
        const step = createApplyEventFiltersStep(mockManager)
        const input = makeInput(1, '$pageview', metrics)

        await step(input)

        expect(incrementSpy).not.toHaveBeenCalled()
    })

    it('uses distinct_id from headers when not on event', async () => {
        mockManager.getFilter.mockReturnValue({
            id: 'f1',
            team_id: 1,
            mode: 'live',
            filter_tree: { type: 'condition', field: 'distinct_id', operator: 'exact', value: 'bot-1' },
        })
        const metrics = new EventFiltersBatchAppMetrics(mockOutputs)
        const step = createApplyEventFiltersStep(mockManager)
        const input = {
            event: makeEvent('$pageview', undefined),
            team: makeTeam(1),
            headers: { token: 'tok', distinct_id: 'bot-1' } as any,
            eventFiltersBatchAppMetrics: metrics,
        }

        const result = await step(input)

        expect(isDropResult(result)).toBe(true)
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

        // Await the side effect to verify it produces
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
