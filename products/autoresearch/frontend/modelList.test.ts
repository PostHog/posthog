import { AutoresearchPipelineApi } from './generated/api.schemas'
import { ModelListSort, filterAndSortPipelines } from './modelList'

function pipeline(overrides: Partial<AutoresearchPipelineApi>): AutoresearchPipelineApi {
    return {
        name: 'Model',
        target_event: 'signed_up',
        status: 'running',
        created_at: '2026-01-01T00:00:00Z',
        not_promoted_reason: null,
        live_training_run: null,
        champion_holdout_auc: 0.85,
        champion_realized_auc: null,
        champion_lift_at_10: null,
        champion_is_preliminary: null,
        ...overrides,
    } as AutoresearchPipelineApi
}

const PIPELINES = [
    pipeline({ name: 'beta live', created_at: '2026-01-05T00:00:00Z' }),
    pipeline({ name: 'Eta weak', champion_holdout_auc: 0.6, created_at: '2025-12-31T00:00:00Z' }),
    pipeline({ name: 'Alpha draft', status: 'draft', created_at: '2026-01-04T00:00:00Z' }),
    pipeline({ name: 'Gamma paused', status: 'paused', created_at: '2026-01-03T00:00:00Z' }),
    pipeline({
        name: 'Delta not live',
        status: 'bootstrapping',
        not_promoted_reason: 'fit failed',
        created_at: '2026-01-02T00:00:00Z',
    }),
    pipeline({
        name: 'Epsilon retrying',
        status: 'bootstrapping',
        not_promoted_reason: 'fit failed',
        live_training_run: {} as AutoresearchPipelineApi['live_training_run'],
        created_at: '2026-01-06T00:00:00Z',
    }),
    pipeline({ name: 'Zeta flags', target_event: '$feature_flag_called', created_at: '2026-01-01T00:00:00Z' }),
]

describe('filterAndSortPipelines', () => {
    test.each<{ sort: ModelListSort; expected: string[] }>([
        {
            sort: 'created',
            expected: [
                'Epsilon retrying',
                'beta live',
                'Alpha draft',
                'Gamma paused',
                'Delta not live',
                'Zeta flags',
                'Eta weak',
            ],
        },
        {
            sort: 'attention',
            expected: [
                'Alpha draft',
                'Gamma paused',
                'Delta not live',
                'Eta weak',
                'Epsilon retrying',
                'beta live',
                'Zeta flags',
            ],
        },
        {
            sort: 'name',
            expected: [
                'Alpha draft',
                'beta live',
                'Delta not live',
                'Epsilon retrying',
                'Eta weak',
                'Gamma paused',
                'Zeta flags',
            ],
        },
    ])('sorts by $sort', ({ sort, expected }) => {
        expect(filterAndSortPipelines(PIPELINES, '', sort).map((p) => p.name)).toEqual(expected)
    })

    test.each([
        { search: 'GAMMA', expected: ['Gamma paused'] },
        { search: '$feature_flag', expected: ['Zeta flags'] },
        { search: 'feature flag', expected: ['Zeta flags'] },
        { search: 'nothing like this', expected: [] },
    ])('search "$search"', ({ search, expected }) => {
        expect(filterAndSortPipelines(PIPELINES, search, 'created').map((p) => p.name)).toEqual(expected)
    })
})
