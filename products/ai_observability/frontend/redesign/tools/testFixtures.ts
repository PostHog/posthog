import type {
    ToolGroupDetailApi,
    ToolListApi,
    ToolListItemApi,
    ToolTraceShareListApi,
} from '../../generated/api.schemas'

export const TOOLS_URL = '/api/projects/:team_id/ai_observability/tools/'
export const TOOL_DETAIL_URL = '/api/projects/:team_id/ai_observability/tools/:key/'
export const TOOL_TRACE_SHARES_URL = '/api/projects/:team_id/ai_observability/tools/trace_shares/'

export function makeToolListItem(overrides: Partial<ToolListItemApi> = {}): ToolListItemApi {
    return {
        key: 'tool-1',
        name: 'search_orders',
        calls: 1240,
        changeLabel: '+18%',
        changeTone: 'neutral',
        traces: 610,
        failureRate: 0.08,
        failures: 99,
        failureState: 'captured',
        isFailing: true,
        onlyToolShare: 0.35,
        lastSeen: '2026-09-07T16:42:00Z',
        series: [150, 170, 160, 190, 180, 200, 190],
        ...overrides,
    }
}

export function makeToolListPage(keys: string[], overrides: Partial<ToolListApi> = {}): ToolListApi {
    return {
        count: keys.length,
        next: null,
        previous: null,
        results: keys.map((key) => makeToolListItem({ key })),
        counts: { total: keys.length, failing: 0, maxCalls: 0 },
        bucketStarts: [],
        nothingCaptured: false,
        order: 'calls',
        ...overrides,
    }
}

export function makeToolTraceShares(shares: [key: string, traceShare: number][]): ToolTraceShareListApi {
    return { items: shares.map(([key, traceShare]) => ({ key, traceShare })) }
}

export function makeToolDetail(overrides: Partial<ToolListItemApi> = {}): ToolGroupDetailApi {
    return {
        item: makeToolListItem(overrides),
        bucketStarts: Array.from({ length: 7 }, (_, day) => `2026-09-0${day + 1}T00:00:00Z`),
        previousSeries: [140, 150, 150, 170, 160, 180, 175],
    }
}
