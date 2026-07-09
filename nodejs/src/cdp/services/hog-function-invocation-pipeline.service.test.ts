import { QuotaLimiting } from '../../common/services/quota-limiting.service'
import { CyclotronJobInvocationHogFunction, HogFunctionInvocationGlobals, HogFunctionType } from '../types'
import { HogExecutorService } from './hog-executor.service'
import { HogFunctionInvocationPipeline } from './hog-function-invocation-pipeline.service'
import { HogFunctionManagerService } from './managers/hog-function-manager.service'
import { HogFunctionMonitoringService } from './monitoring/hog-function-monitoring.service'
import { HogMaskerService } from './monitoring/hog-masker.service'
import { HogWatcherService, HogWatcherState } from './monitoring/hog-watcher.service'

// Mock the rate limiter to give us deterministic control
jest.mock('../../common/services/keyed-rate-limiter.service', () => ({
    KeyedRateLimiterService: jest.fn().mockImplementation(() => ({
        rateLimitGrouped: jest.fn(),
    })),
}))

const config = {
    CDP_RATE_LIMITER_BUCKET_SIZE: 100,
    CDP_RATE_LIMITER_REFILL_RATE: 10,
    CDP_RATE_LIMITER_TTL: 60,
    CDP_OVERFLOW_QUEUE_ENABLED: true,
    CDP_HOG_RUST_VM_SHADOW_FILTER_SAMPLE_RATE: 0,
    MMDB_FILE_LOCATION: '../share/GeoLite2-City.mmdb',
}

function makeHogFunction(overrides: Partial<HogFunctionType> = {}): HogFunctionType {
    return {
        id: overrides.id ?? 'fn-1',
        team_id: 1,
        type: 'destination',
        filters: { source: 'events' },
        enabled: true,
        deleted: false,
        ...overrides,
    } as HogFunctionType
}

function makeInvocation(hogFunction: HogFunctionType, eventUuid = 'evt-1'): CyclotronJobInvocationHogFunction {
    return {
        id: `inv-${hogFunction.id}`,
        teamId: hogFunction.team_id,
        functionId: hogFunction.id,
        queue: 'hog',
        queuePriority: 0,
        state: {
            globals: { event: { uuid: eventUuid } },
        } as any,
        hogFunction,
    } as CyclotronJobInvocationHogFunction
}

function makeGlobals(teamId = 1): HogFunctionInvocationGlobals {
    return { project: { id: teamId } } as HogFunctionInvocationGlobals
}

describe('HogFunctionInvocationPipeline', () => {
    let hogFunctionManager: jest.Mocked<HogFunctionManagerService>
    let hogExecutor: jest.Mocked<HogExecutorService>
    let hogWatcher: jest.Mocked<HogWatcherService>
    let hogMasker: jest.Mocked<HogMaskerService>
    let hogFunctionMonitoringService: jest.Mocked<HogFunctionMonitoringService>
    let quotaLimiting: jest.Mocked<QuotaLimiting>
    let pipeline: HogFunctionInvocationPipeline
    let rateLimitGroupedMock: jest.Mock

    beforeEach(() => {
        hogFunctionManager = {
            getHogFunctionsForTeams: jest.fn().mockResolvedValue({}),
        } as unknown as jest.Mocked<HogFunctionManagerService>

        hogExecutor = {
            buildHogFunctionInvocations: jest.fn().mockResolvedValue({ invocations: [], metrics: [], logs: [] }),
        } as unknown as jest.Mocked<HogExecutorService>

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

        pipeline = new HogFunctionInvocationPipeline(config, {
            hogFunctionManager,
            hogExecutor,
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

    it('returns empty when no hog functions match', async () => {
        const result = await pipeline.buildInvocations([makeGlobals()], {
            hogTypes: ['destination'],
            filterFn: () => true,
        })
        expect(result).toEqual([])
        expect(hogFunctionManager.getHogFunctionsForTeams).toHaveBeenCalledWith(
            [1],
            ['destination'],
            expect.any(Function)
        )
    })

    it('returns invocations for matching hog functions and queues triggered + billing metrics', async () => {
        const fn = makeHogFunction()
        const inv = makeInvocation(fn, 'evt-uuid-1')
        hogExecutor.buildHogFunctionInvocations.mockResolvedValue({ invocations: [inv], metrics: [], logs: [] })
        hogWatcher.getEffectiveStates.mockResolvedValue({ [fn.id]: { state: HogWatcherState.healthy } } as any)
        rateLimitGroupedMock.mockResolvedValue([[null, { isRateLimited: false }]])

        const result = await pipeline.buildInvocations([makeGlobals()], {
            hogTypes: ['destination'],
            filterFn: () => true,
        })

        expect(result).toEqual([inv])
        const metricsCall = hogFunctionMonitoringService.queueAppMetrics.mock.calls.find((c) =>
            c[0].some((m: any) => m.metric_name === 'triggered')
        )
        expect(metricsCall).toBeDefined()
        const billingCall = hogFunctionMonitoringService.queueAppMetrics.mock.calls.find((c) =>
            c[0].some((m: any) => m.metric_name === 'billable_invocation')
        )
        expect(billingCall).toBeDefined()
    })

    it('drops invocations in disabled watcher state', async () => {
        const fn = makeHogFunction()
        const inv = makeInvocation(fn)
        hogExecutor.buildHogFunctionInvocations.mockResolvedValue({ invocations: [inv], metrics: [], logs: [] })
        hogWatcher.getEffectiveStates.mockResolvedValue({ [fn.id]: { state: HogWatcherState.disabled } } as any)
        rateLimitGroupedMock.mockResolvedValue([[null, { isRateLimited: false }]])

        const result = await pipeline.buildInvocations([makeGlobals()], {
            hogTypes: ['destination'],
            filterFn: () => true,
        })

        expect(result).toEqual([])
        expect(hogFunctionMonitoringService.queueAppMetric).toHaveBeenCalledWith(
            expect.objectContaining({ metric_name: 'disabled_permanently' }),
            'hog_function'
        )
    })

    it('routes degraded invocations to hogoverflow queue when overflow enabled', async () => {
        const fn = makeHogFunction()
        const inv = makeInvocation(fn)
        hogExecutor.buildHogFunctionInvocations.mockResolvedValue({ invocations: [inv], metrics: [], logs: [] })
        hogWatcher.getEffectiveStates.mockResolvedValue({ [fn.id]: { state: HogWatcherState.degraded } } as any)
        rateLimitGroupedMock.mockResolvedValue([[null, { isRateLimited: false }]])

        const result = await pipeline.buildInvocations([makeGlobals()], {
            hogTypes: ['destination'],
            filterFn: () => true,
        })

        expect(result).toHaveLength(1)
        expect(result[0].queuePriority).toBe(2)
        expect(result[0].queue).toBe('hogoverflow')
    })

    it('drops quota-limited invocations', async () => {
        const fn = makeHogFunction()
        const inv = makeInvocation(fn)
        hogExecutor.buildHogFunctionInvocations.mockResolvedValue({ invocations: [inv], metrics: [], logs: [] })
        hogWatcher.getEffectiveStates.mockResolvedValue({ [fn.id]: { state: HogWatcherState.healthy } } as any)
        rateLimitGroupedMock.mockResolvedValue([[null, { isRateLimited: false }]])
        quotaLimiting.isTeamQuotaLimited.mockResolvedValue(true)

        const result = await pipeline.buildInvocations([makeGlobals()], {
            hogTypes: ['destination'],
            filterFn: () => true,
        })

        expect(result).toEqual([])
    })

    it('drops masked invocations', async () => {
        const fn = makeHogFunction()
        const inv = makeInvocation(fn)
        hogExecutor.buildHogFunctionInvocations.mockResolvedValue({ invocations: [inv], metrics: [], logs: [] })
        hogWatcher.getEffectiveStates.mockResolvedValue({ [fn.id]: { state: HogWatcherState.healthy } } as any)
        rateLimitGroupedMock.mockResolvedValue([[null, { isRateLimited: false }]])
        hogMasker.filterByMasking.mockResolvedValue({ masked: [inv], notMasked: [] })

        const result = await pipeline.buildInvocations([makeGlobals()], {
            hogTypes: ['destination'],
            filterFn: () => true,
        })

        expect(result).toEqual([])
        expect(hogFunctionMonitoringService.queueAppMetrics).toHaveBeenCalledWith(
            expect.arrayContaining([expect.objectContaining({ metric_name: 'masked' })]),
            'hog_function'
        )
    })

    it('bills only once per unique event uuid even with multiple destinations', async () => {
        const fn1 = makeHogFunction({ id: 'fn-1' })
        const fn2 = makeHogFunction({ id: 'fn-2' })
        const inv1 = makeInvocation(fn1, 'evt-same')
        const inv2 = makeInvocation(fn2, 'evt-same')
        hogExecutor.buildHogFunctionInvocations.mockResolvedValue({ invocations: [inv1, inv2], metrics: [], logs: [] })
        hogWatcher.getEffectiveStates.mockResolvedValue({
            [fn1.id]: { state: HogWatcherState.healthy },
            [fn2.id]: { state: HogWatcherState.healthy },
        } as any)
        rateLimitGroupedMock.mockResolvedValue([
            [null, { isRateLimited: false }],
            [null, { isRateLimited: false }],
        ])

        await pipeline.buildInvocations([makeGlobals()], {
            hogTypes: ['destination'],
            filterFn: () => true,
        })

        const billingMetrics = hogFunctionMonitoringService.queueAppMetrics.mock.calls
            .flatMap((c) => c[0])
            .filter((m: any) => m.metric_name === 'billable_invocation')
        expect(billingMetrics).toHaveLength(1)
    })

    it('does not drop rate-limited invocations (monitoring-only)', async () => {
        const fn = makeHogFunction()
        const inv = makeInvocation(fn)
        hogExecutor.buildHogFunctionInvocations.mockResolvedValue({ invocations: [inv], metrics: [], logs: [] })
        hogWatcher.getEffectiveStates.mockResolvedValue({ [fn.id]: { state: HogWatcherState.healthy } } as any)
        rateLimitGroupedMock.mockResolvedValue([[null, { isRateLimited: true }]])

        const result = await pipeline.buildInvocations([makeGlobals()], {
            hogTypes: ['destination'],
            filterFn: () => true,
        })

        expect(result).toHaveLength(1)
    })
})
