import { QuotaLimiting } from '../../common/services/quota-limiting.service'
import { HogFunctionInvocationGlobals } from '../types'
import { HogFlowInvocationPipeline } from './hog-flow-invocation-pipeline.service'
import { HogFlowExecutorService } from './hogflows/hogflow-executor.service'
import { HogFlowManagerService } from './hogflows/hogflow-manager.service'
import { HogFunctionMonitoringService } from './monitoring/hog-function-monitoring.service'
import { HogMaskerService } from './monitoring/hog-masker.service'
import { HogWatcherService, HogWatcherState } from './monitoring/hog-watcher.service'

jest.mock('../../common/services/keyed-rate-limiter.service', () => ({
    KeyedRateLimiterService: jest.fn().mockImplementation(() => ({
        rateLimitGrouped: jest.fn(),
    })),
}))

const config = {
    CDP_RATE_LIMITER_BUCKET_SIZE: 100,
    CDP_RATE_LIMITER_REFILL_RATE: 10,
    CDP_RATE_LIMITER_TTL: 60,
}

function makeHogFlowInvocation(hogFlowId = 'flow-1', overrides: { billable_action_types?: string[] } = {}) {
    return {
        id: `inv-${hogFlowId}`,
        teamId: 1,
        functionId: hogFlowId,
        queue: 'hogflow',
        queuePriority: 0,
        hogFlow: { id: hogFlowId, name: 'test flow', billable_action_types: overrides.billable_action_types ?? [] },
        state: { event: { uuid: 'evt-1' } },
        person: undefined,
    } as any
}

function makeGlobals(teamId = 1): HogFunctionInvocationGlobals {
    return { project: { id: teamId } } as HogFunctionInvocationGlobals
}

describe('HogFlowInvocationPipeline', () => {
    let hogFlowManager: jest.Mocked<HogFlowManagerService>
    let hogFlowExecutor: jest.Mocked<HogFlowExecutorService>
    let hogWatcher: jest.Mocked<HogWatcherService>
    let hogMasker: jest.Mocked<HogMaskerService>
    let hogFunctionMonitoringService: jest.Mocked<HogFunctionMonitoringService>
    let quotaLimiting: jest.Mocked<QuotaLimiting>
    let pipeline: HogFlowInvocationPipeline
    let rateLimitGroupedMock: jest.Mock

    beforeEach(() => {
        hogFlowManager = {
            getHogFlowsForTeams: jest.fn().mockResolvedValue({}),
        } as unknown as jest.Mocked<HogFlowManagerService>

        hogFlowExecutor = {
            buildHogFlowInvocations: jest.fn().mockResolvedValue({ invocations: [], metrics: [], logs: [] }),
        } as unknown as jest.Mocked<HogFlowExecutorService>

        hogWatcher = {
            getEffectiveStates: jest.fn().mockResolvedValue({}),
        } as unknown as jest.Mocked<HogWatcherService>

        hogMasker = {
            filterByMasking: jest.fn((invocations) => Promise.resolve({ masked: [], notMasked: invocations })),
        } as unknown as jest.Mocked<HogMaskerService>

        hogFunctionMonitoringService = {
            queueAppMetrics: jest.fn(),
            queueAppMetric: jest.fn(),
            queueLogs: jest.fn(),
        } as unknown as jest.Mocked<HogFunctionMonitoringService>

        quotaLimiting = {
            isTeamQuotaLimited: jest.fn().mockResolvedValue(false),
        } as unknown as jest.Mocked<QuotaLimiting>

        pipeline = new HogFlowInvocationPipeline(config, {
            hogFlowManager,
            hogFlowExecutor,
            hogWatcher,
            hogWatcherMirror: null,
            hogMasker,
            hogFunctionMonitoringService,
            quotaLimiting,
            redis: {} as any,
            valkeyShadow: null,
        })

        rateLimitGroupedMock = (pipeline as any).hogRateLimiter.rateLimitGrouped as jest.Mock
        rateLimitGroupedMock.mockResolvedValue([])
    })

    it('returns empty when no hogflows match', async () => {
        const result = await pipeline.buildInvocations([makeGlobals()])
        expect(result).toEqual([])
        expect(hogFlowManager.getHogFlowsForTeams).toHaveBeenCalledWith([1])
    })

    it('returns invocations for matching hogflows and queues triggered metric', async () => {
        const inv = makeHogFlowInvocation()
        hogFlowExecutor.buildHogFlowInvocations.mockResolvedValue({ invocations: [inv], metrics: [], logs: [] })
        hogWatcher.getEffectiveStates.mockResolvedValue({ [inv.hogFlow.id]: { state: HogWatcherState.healthy } } as any)
        rateLimitGroupedMock.mockResolvedValue([[null, { isRateLimited: false }]])

        const result = await pipeline.buildInvocations([makeGlobals()])

        expect(result).toEqual([inv])
        expect(hogFunctionMonitoringService.queueAppMetrics).toHaveBeenCalledWith(
            expect.arrayContaining([expect.objectContaining({ metric_name: 'triggered' })]),
            'hog_flow'
        )
    })

    it('drops rate-limited invocations with metric + log', async () => {
        const inv = makeHogFlowInvocation()
        hogFlowExecutor.buildHogFlowInvocations.mockResolvedValue({ invocations: [inv], metrics: [], logs: [] })
        hogWatcher.getEffectiveStates.mockResolvedValue({ [inv.hogFlow.id]: { state: HogWatcherState.healthy } } as any)
        rateLimitGroupedMock.mockResolvedValue([[null, { isRateLimited: true }]])

        const result = await pipeline.buildInvocations([makeGlobals()])

        expect(result).toEqual([])
        expect(hogFunctionMonitoringService.queueAppMetric).toHaveBeenCalledWith(
            expect.objectContaining({ metric_name: 'rate_limited' }),
            'hog_flow'
        )
        expect(hogFunctionMonitoringService.queueLogs).toHaveBeenCalled()
    })

    it('drops quota-limited invocations', async () => {
        // hogflow quota helper short-circuits when billable_action_types is empty
        const inv = makeHogFlowInvocation('flow-1', { billable_action_types: ['function_email'] })
        hogFlowExecutor.buildHogFlowInvocations.mockResolvedValue({ invocations: [inv], metrics: [], logs: [] })
        hogWatcher.getEffectiveStates.mockResolvedValue({ [inv.hogFlow.id]: { state: HogWatcherState.healthy } } as any)
        rateLimitGroupedMock.mockResolvedValue([[null, { isRateLimited: false }]])
        quotaLimiting.isTeamQuotaLimited.mockResolvedValue(true)

        const result = await pipeline.buildInvocations([makeGlobals()])
        expect(result).toEqual([])
    })

    it('drops invocations for disabled hogflows', async () => {
        const inv = makeHogFlowInvocation()
        hogFlowExecutor.buildHogFlowInvocations.mockResolvedValue({ invocations: [inv], metrics: [], logs: [] })
        hogWatcher.getEffectiveStates.mockResolvedValue({
            [inv.hogFlow.id]: { state: HogWatcherState.disabled },
        } as any)
        rateLimitGroupedMock.mockResolvedValue([[null, { isRateLimited: false }]])

        const result = await pipeline.buildInvocations([makeGlobals()])

        expect(result).toEqual([])
        expect(hogFunctionMonitoringService.queueAppMetric).toHaveBeenCalledWith(
            expect.objectContaining({ metric_name: 'disabled_permanently' }),
            'hog_flow'
        )
    })

    it('sets queuePriority=2 for degraded hogflows but does not change queue', async () => {
        const inv = makeHogFlowInvocation()
        hogFlowExecutor.buildHogFlowInvocations.mockResolvedValue({ invocations: [inv], metrics: [], logs: [] })
        hogWatcher.getEffectiveStates.mockResolvedValue({
            [inv.hogFlow.id]: { state: HogWatcherState.degraded },
        } as any)
        rateLimitGroupedMock.mockResolvedValue([[null, { isRateLimited: false }]])

        const result = await pipeline.buildInvocations([makeGlobals()])

        expect(result).toHaveLength(1)
        expect(result[0].queuePriority).toBe(2)
        expect(result[0].queue).toBe('hogflow')
    })

    it('drops masked invocations', async () => {
        const inv = makeHogFlowInvocation()
        hogFlowExecutor.buildHogFlowInvocations.mockResolvedValue({ invocations: [inv], metrics: [], logs: [] })
        hogWatcher.getEffectiveStates.mockResolvedValue({ [inv.hogFlow.id]: { state: HogWatcherState.healthy } } as any)
        rateLimitGroupedMock.mockResolvedValue([[null, { isRateLimited: false }]])
        hogMasker.filterByMasking.mockResolvedValue({ masked: [inv], notMasked: [] })

        const result = await pipeline.buildInvocations([makeGlobals()])

        expect(result).toEqual([])
        expect(hogFunctionMonitoringService.queueAppMetrics).toHaveBeenCalledWith(
            expect.arrayContaining([expect.objectContaining({ metric_name: 'masked' })]),
            'hog_flow'
        )
    })
})
