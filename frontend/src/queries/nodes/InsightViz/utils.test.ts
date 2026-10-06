import { Node, NodeKind } from '~/queries/schema/schema-general'
import { InsightModel, InsightType } from '~/types'

import { extractValidationErrorCode, getDefaultQuery, getQueryBasedInsightModel } from './utils'

describe('extractValidationErrorCode', () => {
    test.each([
        ['code set directly on the error (async polling shape)', { status: 400, code: 'some_code' }, 'some_code'],
        ['code in the response body (sync DRF shape)', { status: 512, data: { code: 'some_code' } }, 'some_code'],
        [
            'memory-limit error (status 513)',
            { status: 513, code: 'clickhouse_memory_limit_exceeded' },
            'clickhouse_memory_limit_exceeded',
        ],
        ['non-validation status', { status: 500, code: 'some_code' }, null],
        ['no error', null, null],
    ])('%s', (_name, error, expected) => {
        expect(extractValidationErrorCode(error)).toBe(expected)
    })
})

describe('getQueryBasedInsightModel', () => {
    it.each([
        [
            'derives dashboards from dashboard_tiles when the response omits the deprecated field',
            {
                dashboard_tiles: [
                    { id: 10, dashboard_id: 1 },
                    { id: 11, dashboard_id: 2 },
                ],
            },
            [1, 2],
        ],
        [
            'keeps the server-provided dashboards value when present',
            { dashboards: [3], dashboard_tiles: [{ id: 10, dashboard_id: 1 }] },
            [3],
        ],
        ['leaves dashboards undefined when neither field is present', {}, undefined],
        [
            'derives dashboards from dashboard_tiles when dashboards is null',
            { dashboards: null, dashboard_tiles: [{ id: 10, dashboard_id: 1 }] },
            [1],
        ],
        [
            'excludes soft-deleted tiles when deriving dashboards',
            {
                dashboard_tiles: [
                    { id: 10, dashboard_id: 1 },
                    { id: 11, dashboard_id: 2, deleted: true },
                ],
            },
            [1],
        ],
    ])('%s', (_name, input, expected) => {
        const result = getQueryBasedInsightModel(input as Partial<InsightModel>)
        expect(result.dashboards).toEqual(expected)
    })

    it('leaves the rest of the insight untouched', () => {
        const query = { kind: NodeKind.TrendsQuery } as Node
        const result = getQueryBasedInsightModel({ id: 7, name: 'Pageviews', query })

        expect(result).toEqual({ id: 7, name: 'Pageviews', query })
    })
})

describe('getDefaultQuery with default filters', () => {
    it.each([
        InsightType.TRENDS,
        InsightType.FUNNELS,
        InsightType.RETENTION,
        InsightType.PATHS,
        InsightType.STICKINESS,
        InsightType.LIFECYCLE,
    ])('turns on applyDefaultFilters for the %s query', (insightType) => {
        const query = getDefaultQuery(insightType, false, true)

        expect(query.kind).toBe(NodeKind.InsightVizNode)
        expect((query as any).source.applyDefaultFilters).toBe(true)
    })

    it('keeps the test account toggle and the default filters independent', () => {
        const query = getDefaultQuery(InsightType.TRENDS, true, true) as any

        expect(query.source.filterTestAccounts).toBe(true)
        expect(query.source.applyDefaultFilters).toBe(true)
    })

    it('leaves the flag out when the project has no default filters', () => {
        expect((getDefaultQuery(InsightType.TRENDS, false, false) as any).source).not.toHaveProperty(
            'applyDefaultFilters'
        )
        expect((getDefaultQuery(InsightType.TRENDS, false) as any).source).not.toHaveProperty('applyDefaultFilters')
    })

    it.each([InsightType.SQL, InsightType.JSON, InsightType.HOG])('does not touch %s queries', (insightType) => {
        expect(getDefaultQuery(insightType, false, true)).toEqual(getDefaultQuery(insightType, false))
    })
})
