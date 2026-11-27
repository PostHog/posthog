import type { ErrorListApi, ErrorListCountsApi, ErrorListItemApi } from '../../generated/api.schemas'

export const ERRORS_URL = '/api/projects/:team_id/ai_observability/errors/'

const NO_COUNTS: ErrorListCountsApi = { total: 0, increasing: 0, decreasing: 0, maxOccurrences: 0 }

export function makeErrorListItem(overrides: Partial<ErrorListItemApi> = {}): ErrorListItemApi {
    return {
        key: 'error-1',
        message: 'RateLimitError: request limit reached for the example-model deployment, retry after 20 seconds',
        occurrences: 128,
        changeLabel: '+40%',
        changeTone: 'bad',
        trend: 'increasing',
        traces: 96,
        users: 31,
        models: ['example-model-large', 'example-model-small'],
        lastSeen: '2026-09-07T16:42:00Z',
        series: [12, 15, 9, 20, 22, 25, 25],
        ...overrides,
    }
}

export function makeErrorListPage(keys: string[], overrides: Partial<ErrorListApi> = {}): ErrorListApi {
    return {
        count: keys.length,
        next: null,
        previous: null,
        results: keys.map((key) => makeErrorListItem({ key })),
        counts: NO_COUNTS,
        bucketStarts: [],
        nothingCaptured: false,
        order: 'occurrences',
        ...overrides,
    }
}
