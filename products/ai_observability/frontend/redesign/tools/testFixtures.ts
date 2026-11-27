import type { ToolListApi, ToolListItemApi } from '../../generated/api.schemas'

export const TOOLS_URL = '/api/projects/:team_id/ai_observability/tools/'

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
