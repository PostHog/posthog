import { router } from 'kea-router'

import { BIConfig, BIField, BIVisualizationNode } from '~/queries/schema/schema-business-intelligence'
import { NodeKind } from '~/queries/schema/schema-general'
import { insightOnDashboard, tileFromInsight } from '~/scenes/dashboard/dashboardLogic.testHelpers'
import { initKeaTests } from '~/test/init'
import { ChartDisplayType, DashboardTile } from '~/types'

import { biDashboardCrossFilterLogic } from './biDashboardCrossFilterLogic'
import { applyBIDashboardSelection, createBIDashboardSelection, getBIDashboardTargets } from './biDashboardCrossFilters'
import { getBIDashboardFilterLink, readBIDashboardFilterLink } from './biDashboardFilterLinks'
import { buildBIQuery, DEFAULT_BI_CONFIG, getBIResultDimensions } from './biEditorTypes'
import { getBIVisualizationSource } from './biQueryResults'

const country: BIField = {
    id: 'country',
    name: 'Country',
    expression: 'country',
    type: 'string',
    source: { table: 'orders' },
}
const base: BIConfig = {
    ...DEFAULT_BI_CONFIG,
    source: country.source,
    rows: [country],
    chartType: ChartDisplayType.ActionsBar,
}
function worksheet(config: BIConfig = base): BIVisualizationNode {
    return { ...buildBIQuery(config)!.node, kind: NodeKind.BIVisualizationNode, config }
}
function mark(query: BIVisualizationNode, value: unknown): Record<string, unknown> {
    return { [getBIResultDimensions(query.config)[0].column]: value }
}

describe('dashboard worksheet cross filters', () => {
    it.each(['US', null, ''])('links only the selected dimensions and restores %j after tiles load', (value) => {
        initKeaTests()
        const query = worksheet()
        const url = getBIDashboardFilterLink(
            'http://localhost/project/1/dashboard/1?date_from=all#other=value',
            1,
            1,
            query.config,
            { ...mark(query, value), count: 10, unrelated: 'not part of the selection' }
        )
        const hash = new URLSearchParams(url.split('#')[1])
        expect(url).toContain('?date_from=all')
        expect(hash.get('other')).toBe('value')
        expect(readBIDashboardFilterLink(hash.get('bi_filter'))?.record).toEqual(mark(query, value))
        const clearedUrl = getBIDashboardFilterLink(
            new URL(url, 'http://localhost').href,
            1,
            1,
            query.config,
            mark(query, value),
            true
        )
        expect(clearedUrl).not.toContain('bi_filter=')
        expect(clearedUrl).toContain('?date_from=all#other=value')
        router.actions.push(url)
        const logic = biDashboardCrossFilterLogic({ dashboardId: 1, tiles: [] })
        const unmount = logic.mount()
        try {
            expect(logic.values.selection).toBeNull()
            const other = biDashboardCrossFilterLogic({ dashboardId: 2 })
            const unmountOther = other.mount()
            other.actions.setSelection(null)
            expect(readBIDashboardFilterLink(router.values.currentLocation.hashParams.bi_filter)?.dashboardId).toBe(1)
            unmountOther()
            const tiles = [1, 2].map((id) => tileFromInsight({ ...insightOnDashboard(id, [1]), query }, id))
            biDashboardCrossFilterLogic({ dashboardId: 1, tiles })
            expect(logic.values.selection?.selection).toEqual(
                createBIDashboardSelection(1, '', query, mark(query, value))?.selection
            )
            expect(Object.keys(logic.values.targets)).toEqual(['2'])
            logic.actions.setSelection(null)
            expect(logic.values.selection).toBeNull()
            expect(router.values.currentLocation.hashParams.bi_filter).toBeUndefined()
            expect(router.values.currentLocation.hashParams.other).toBe('value')
        } finally {
            unmount()
            window.history.replaceState({}, '', '/')
        }
    })

    it.each(['bad-json', 'null', '{"dashboardId":1,"tileId":1,"record":{"status":{}}}'])(
        'ignores malformed result links: %s',
        (raw) => {
            expect(readBIDashboardFilterLink(raw)).toBeNull()
        }
    )
    it.each([
        ["Cote d'Ivoire", "country = 'Cote d\\'Ivoire'"],
        [null, 'country IS NULL'],
        ['', "country IN ('')"],
    ])('adds %s before aggregation without mutating filters, variables, or presentation', (value, expression) => {
        const target = worksheet({
            ...base,
            filters: [
                { field: { ...country, id: 'existing' }, operator: 'equals', value: 'US' },
                { field: { ...country, id: 'second' }, operator: 'equals', value: 'GB' },
            ],
            rowFilterGroup: { operator: 'OR', filters: ['existing', 'second'], groups: [] },
        })
        target.source.filters = { dateRange: { date_from: '-30d' }, filterTestAccounts: true }
        target.source.variables = { v: { variableId: 'v', code_name: 'plan', value: 'pro' } }
        target.chartSettings = { showLegend: false }
        const original = structuredClone(target)
        const active = createBIDashboardSelection(1, 'Countries', worksheet(), mark(worksheet(), value))!
        const filtered = applyBIDashboardSelection(target, active)!
        const sql = getBIVisualizationSource(filtered).query
        expect(sql).toContain(expression)
        expect(sql).toContain("(country = 'US') OR (country = 'GB')")
        expect(sql.indexOf(expression)).toBeLessThan(sql.indexOf('GROUP BY'))
        expect(filtered.source.filters).toEqual(target.source.filters)
        expect(filtered.source.variables).toEqual(target.source.variables)
        expect(filtered.chartSettings).toEqual(target.chartSettings)
        expect(target).toEqual(original)
    })

    it('filters the source date bucket even when the target has a different grain', () => {
        const date: BIField = { ...country, id: 'date', expression: 'timestamp', type: 'datetime', dateBucket: 'month' }
        const source = worksheet({ ...base, rows: [date] })
        const active = createBIDashboardSelection(1, 'Monthly', source, mark(source, '2026-01-01'))!
        const filtered = applyBIDashboardSelection(worksheet(), active)!
        expect(getBIVisualizationSource(filtered).query).toContain("toStartOfMonth(timestamp) = '2026-01-01'")
        expect(filtered.config.rows).toEqual([country])
    })

    it('only targets other worksheets on the exact source and connection', () => {
        const query = worksheet()
        const active = createBIDashboardSelection(1, 'Countries', query, mark(query, 'US'))!
        const tiles = [
            { id: 1, insight: { query } },
            { id: 2, insight: { query } },
            { id: 3, insight: { query: { ...query, config: { ...base, source: { table: 'customers' } } } } },
            {
                id: 4,
                insight: {
                    query: { ...query, config: { ...base, source: { ...base.source, connectionId: 'other' } } },
                },
            },
            { id: 5, insight: { query: { ...query, config: { ...base, querySnapshot: query.source } } } },
            { id: 6, insight: { query: { kind: NodeKind.DataVisualizationNode, source: query.source } } },
            { id: 7, text: { body: 'Notes' } },
        ] as DashboardTile[]
        expect(Object.keys(getBIDashboardTargets(tiles, active))).toEqual(['2'])
    })

    it.each([
        [{ bi_comparison: 'Previous period' }, {}, 'US'],
        [{}, { topN: { fieldId: 'country', count: 3, measureIndex: 0, includeOther: true } }, 'Other'],
        [{ count: 10 }, {}, undefined],
    ])('rejects unsupported marks without silently applying a partial segment', (record, extra, value) => {
        const query = worksheet({ ...base, ...extra })
        expect(
            createBIDashboardSelection(1, 'Countries', query, {
                ...record,
                ...(value !== undefined ? mark(query, value) : {}),
            })
        ).toBeNull()
    })

    it.each(['dashboard filters', 'variables', 'presentation', 'source', 'dimensions'])(
        'keeps selections only when their meaning survives a change to %s',
        (change) => {
            initKeaTests()
            router.actions.push('/dashboard/1')
            const query = worksheet()
            const tiles = [1, 2].map((id) => tileFromInsight({ ...insightOnDashboard(id, [1]), query }, id))
            const logic = biDashboardCrossFilterLogic({ dashboardId: 1, tiles })
            const unmount = logic.mount()
            try {
                logic.actions.selectMark(1, 'Countries', query, mark(query, 'US'))
                const updated: BIVisualizationNode = JSON.parse(JSON.stringify(query))
                if (change === 'dashboard filters') {
                    updated.source.filters = { dateRange: { date_from: '-30d' }, filterTestAccounts: true }
                } else if (change === 'variables') {
                    updated.source.variables = { plan: { variableId: 'plan', code_name: 'plan', value: 'pro' } }
                } else if (change === 'presentation') {
                    updated.chartSettings = { showLegend: false }
                } else if (change === 'source') {
                    updated.config.source = { table: 'customers' }
                } else {
                    updated.config.rows = [{ ...country, expression: 'billing_country' }]
                }
                biDashboardCrossFilterLogic({
                    dashboardId: 1,
                    tiles: tiles.map((tile) => ({ ...tile, insight: { ...tile.insight!, query: updated } })),
                })
                const shouldKeep = !['source', 'dimensions'].includes(change)
                expect(!!logic.values.selection).toBe(shouldKeep)
                expect(!!router.values.currentLocation.hashParams.bi_filter).toBe(shouldKeep)
                if (shouldKeep) {
                    expect(logic.values.targets[2].source.filters).toEqual(updated.source.filters)
                    expect(logic.values.targets[2].source.variables).toEqual(updated.source.variables)
                }
            } finally {
                unmount()
            }
        }
    )

    it('toggles a selection, replaces it from another tile, clears on exit, and isolates dashboards', () => {
        initKeaTests()
        router.actions.push('/dashboard/1', { date_from: '-7d' }, { other: 'preserved' })
        const originalPath = router.values.currentLocation.pathname
        const query = worksheet()
        const tiles = [1, 2].map((id) => tileFromInsight({ ...insightOnDashboard(id, [1]), query }, id))
        const logic = biDashboardCrossFilterLogic({ dashboardId: 1, tiles })
        const other = biDashboardCrossFilterLogic({ dashboardId: 2 })
        const unmount = logic.mount()
        const unmountOther = other.mount()
        try {
            logic.actions.selectMark(1, 'Countries', query, mark(query, 'US'))
            expect(logic.values.selection?.tileId).toBe(1)
            expect(readBIDashboardFilterLink(router.values.currentLocation.hashParams.bi_filter)?.record).toEqual(
                mark(query, 'US')
            )
            expect(other.values.selection).toBeNull()
            expect(router.values.currentLocation.pathname).toBe(originalPath)
            expect(router.values.currentLocation.searchParams.date_from).toBe('-7d')
            expect(router.values.currentLocation.hashParams.other).toBe('preserved')
            logic.actions.selectMark(1, 'Countries', query, mark(query, 'US'))
            expect(logic.values.selection).toBeNull()
            logic.actions.selectMark(2, 'Other chart', query, mark(query, 'GB'))
            expect(logic.values.selection?.tileId).toBe(2)
            biDashboardCrossFilterLogic({ dashboardId: 1, tiles: [tiles[0]] })
            expect(logic.values.selection).toBeNull()
            logic.actions.selectMark(1, 'Countries', query, mark(query, 'US'))
            logic.actions.setSelection(null)
            expect(logic.values.selection).toBeNull()
        } finally {
            unmount()
            unmountOther()
        }
    })
})
