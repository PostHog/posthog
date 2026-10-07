import { BIConfig, BIField } from '~/queries/schema/schema-business-intelligence'

import {
    BIEditorView,
    DEFAULT_BI_CONFIG,
    buildBIFilterOptionsQuery,
    buildBIQuery,
    buildBIRowsQuery,
    parseBIEditorState,
} from './biEditorTypes'
import { moveBICondition } from './biFilterGroups'

const field = (name: string): BIField => ({
    id: name,
    name,
    expression: name,
    type: 'string',
    source: { table: 'events' },
})
const config: BIConfig = {
    ...DEFAULT_BI_CONFIG,
    source: { table: 'events' },
    filters: ['event', 'properties.plan', 'properties.country'].map((name) => ({
        field: field(name),
        operator: 'equals',
        value: 'example',
    })),
}

describe('BI filter groups', () => {
    it('moves conditions into nested groups and preserves precedence in charts, rows and suggestions', () => {
        const group = moveBICondition(
            {
                operator: 'AND',
                filters: config.filters.map((filter) => filter.field.id),
                groups: [{ operator: 'OR', filters: [], groups: [] }],
            },
            'event',
            [0]
        )
        const nested = moveBICondition(group, 'properties.plan', [0])
        const worksheet = { ...config, rowFilterGroup: nested }
        const parsed = parseBIEditorState(BIEditorView.BI, worksheet)!.config
        expect(parsed.rowFilterGroup).toEqual(nested)
        for (const query of [buildBIQuery(parsed)!.query, buildBIRowsQuery(parsed)!.query]) {
            expect(query).toContain(
                "(properties.country = 'example') AND ((event = 'example') OR (properties.plan = 'example'))"
            )
            expect(query.match(/event = 'example'/g)).toHaveLength(1)
        }
        const suggestions = buildBIFilterOptionsQuery(parsed, 0)!.query
        expect(suggestions).not.toContain("event = 'example'")
        expect(suggestions).toContain("properties.plan = 'example'")
        expect(suggestions).toContain("properties.country = 'example'")
        expect(
            buildBIQuery({ ...parsed, filters: parsed.filters.map((filter) => ({ ...filter, enabled: false })) })!.query
        ).not.toContain("= 'example'")
    })

    it.each([
        { rowFilterGroup: { operator: 'X', filters: [], groups: [] } },
        { rowFilterGroup: { operator: 'OR', filters: [], groups: [null] } },
        { resultFilters: [{ id: 'bad', measureIndex: -1, operator: 'equals', value: '1' }] },
        { resultFilters: [{ id: 'bad', measureIndex: 0, operator: 'custom', value: '1' }] },
    ])('rejects malformed persisted filter configuration: %j', (update) => {
        expect(parseBIEditorState(BIEditorView.BI, { ...config, ...update })).toBeNull()
    })

    it('filters the implicit count and fails closed for missing measures', () => {
        const filter = { id: 'count', measureIndex: 0, operator: 'greater_than' as const, value: '9007199254740993' }
        expect(buildBIQuery({ ...config, resultFilters: [filter] })!.query).toContain('count > 9007199254740993')
        expect(buildBIQuery({ ...config, resultFilters: [{ ...filter, measureIndex: 1 }] })).toBeNull()
    })
})
