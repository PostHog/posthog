import { expectLogic } from 'kea-test-utils'

import { DataNodeLogicProps, dataNodeLogic } from '~/queries/nodes/DataNode/dataNodeLogic'
import { performQuery } from '~/queries/query'
import { setLatestVersionsOnQuery } from '~/queries/schema/query-versions'
import { MarketingAnalyticsAggregatedQuery, NodeKind } from '~/queries/schema/schema-general'
import { initKeaTests } from '~/test/init'

import {
    PRECOMPUTE_MAX_POLLS,
    PRECOMPUTE_POLL_INTERVAL_MS,
    marketingAnalyticsPrecomputeLogic,
} from './marketingAnalyticsPrecomputeLogic'

jest.mock('~/queries/query', () => ({
    __esModules: true,
    ...jest.requireActual('~/queries/query'),
    performQuery: jest.fn(),
}))
const mockedQuery = performQuery as jest.MockedFunction<typeof performQuery>

const notReadyResponse = { results: {}, precomputeNotReady: true }
const readyResponse = { results: { spend: { value: 10 } }, precomputeNotReady: false }
const aggregatedQuery = (dateFrom: string): MarketingAnalyticsAggregatedQuery =>
    setLatestVersionsOnQuery({
        kind: NodeKind.MarketingAnalyticsAggregatedQuery,
        properties: [],
        dateRange: { date_from: dateFrom },
    })

describe('marketingAnalyticsPrecomputeLogic', () => {
    let rechecks = 0

    beforeEach(() => {
        initKeaTests()
        jest.useFakeTimers()
        mockedQuery.mockReset()
        rechecks = 0
    })
    afterEach(() => {
        jest.useRealTimers()
    })

    const mount = (dateFrom: string): ReturnType<typeof marketingAnalyticsPrecomputeLogic.build> => {
        const props: DataNodeLogicProps = { key: 'marketing-overview', query: aggregatedQuery(dateFrom) }
        dataNodeLogic(props).mount()
        const logic = marketingAnalyticsPrecomputeLogic(props)
        logic.mount()
        return logic
    }

    it.each([
        { name: 'stops once the warmed data arrives', readyAfter: 2, failOn: null, expectedRechecks: 2 },
        { name: 'keeps polling after a failed re-read', readyAfter: 3, failOn: 1, expectedRechecks: 3 },
        {
            name: 'gives up after the poll budget when the warm never lands',
            readyAfter: null,
            failOn: null,
            expectedRechecks: PRECOMPUTE_MAX_POLLS,
        },
    ])('$name', async ({ readyAfter, failOn, expectedRechecks }) => {
        mockedQuery.mockImplementation(async (_query, _methodOptions, refresh) => {
            if (refresh === 'force_blocking') {
                rechecks += 1
                if (rechecks === failOn) {
                    throw new Error('timeout')
                }
            }
            return readyAfter !== null && rechecks >= readyAfter ? readyResponse : notReadyResponse
        })
        const logic = mount('-30d')

        await jest.advanceTimersByTimeAsync(PRECOMPUTE_POLL_INTERVAL_MS * (PRECOMPUTE_MAX_POLLS + 5))
        await expectLogic(logic).toFinishAllListeners()

        expect(rechecks).toBe(expectedRechecks)
        expect(logic.values.autoRefreshing).toBe(false)
        expect(logic.values.notReady).toBe(readyAfter === null)
    })

    it.each([
        {
            name: 'stops polling when a dashboard hands the tile ready results without a load',
            loaded: notReadyResponse,
            handed: readyResponse,
            expectedRechecks: 0,
        },
        {
            name: 'polls when a dashboard hands a ready tile not-ready results without a load',
            loaded: readyResponse,
            handed: notReadyResponse,
            expectedRechecks: 1,
        },
    ])('$name', async ({ loaded, handed, expectedRechecks }) => {
        mockedQuery.mockImplementation(async (_query, _methodOptions, refresh) => {
            if (refresh === 'force_blocking') {
                rechecks += 1
                return readyResponse
            }
            return loaded
        })
        const logic = mount('-30d')
        await jest.advanceTimersByTimeAsync(0)
        expect(logic.values.notReady).toBe(loaded === notReadyResponse)

        dataNodeLogic({ key: 'marketing-overview', query: aggregatedQuery('-30d') }).actions.setResponse(handed)
        await jest.advanceTimersByTimeAsync(PRECOMPUTE_POLL_INTERVAL_MS)

        expect(rechecks).toBe(expectedRechecks)
        expect(logic.values.notReady).toBe(false)
    })

    it('re-reads right away when the tile mounts with not-ready cached results', async () => {
        mockedQuery.mockImplementation(async (_query, _methodOptions, refresh) => {
            if (refresh === 'force_blocking') {
                rechecks += 1
            }
            return readyResponse
        })
        const props: DataNodeLogicProps = {
            key: 'marketing-overview',
            query: aggregatedQuery('-30d'),
            cachedResults: notReadyResponse,
        }
        dataNodeLogic(props).mount()
        const logic = marketingAnalyticsPrecomputeLogic(props)
        logic.mount()
        await jest.advanceTimersByTimeAsync(0)

        expect(rechecks).toBe(1)
        expect(logic.values.notReady).toBe(false)
    })

    it.each([
        { name: 'starts a fresh budget when the query changes', key: 'marketing-overview', cached: false },
        {
            name: 'starts a fresh budget when a dashboard hands results for a new query',
            key: 'dashboard-marketing-overview',
            cached: true,
        },
    ])('$name', async ({ key, cached }) => {
        mockedQuery.mockImplementation(async (_query, _methodOptions, refresh) => {
            if (refresh === 'force_blocking') {
                rechecks += 1
            }
            return notReadyResponse
        })
        const tileProps = (dateFrom: string): DataNodeLogicProps => ({
            key,
            query: aggregatedQuery(dateFrom),
            ...(cached ? { cachedResults: { ...notReadyResponse } } : {}),
        })
        dataNodeLogic(tileProps('-30d')).mount()
        const logic = marketingAnalyticsPrecomputeLogic(tileProps('-30d'))
        logic.mount()
        await jest.advanceTimersByTimeAsync(PRECOMPUTE_POLL_INTERVAL_MS * (PRECOMPUTE_MAX_POLLS + 5))
        expect(logic.values.autoRefreshing).toBe(false)
        const spentRechecks = rechecks

        dataNodeLogic(tileProps('-90d'))
        marketingAnalyticsPrecomputeLogic(tileProps('-90d'))
        await jest.advanceTimersByTimeAsync(0)
        await expectLogic(logic).toFinishAllListeners()

        expect(logic.values).toMatchObject({ notReady: true, autoRefreshing: true, polls: 0 })
        await jest.advanceTimersByTimeAsync(PRECOMPUTE_POLL_INTERVAL_MS)
        expect(rechecks).toBe(spentRechecks + 1)
    })
})
