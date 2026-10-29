import { BIConfig, BIField, BIHierarchy, BIVisualizationNode } from '~/queries/schema/schema-business-intelligence'
import { NodeKind } from '~/queries/schema/schema-general'
import { ChartDisplayType } from '~/types'

import { getBIDrillSelection } from './biDrilldown'
import {
    BIEditorView,
    buildBIQuery,
    DEFAULT_BI_CONFIG,
    getBIResultDimensions,
    parseBIEditorState,
} from './biEditorTypes'
import { getBIHierarchyDrills, getBIHierarchyParent, hierarchyError } from './biHierarchies'

const field = (name: string): BIField => ({
    id: name,
    name,
    expression: `properties.${name}`,
    type: 'string',
    source: { table: 'events' },
})
const geography: BIHierarchy = { id: 'geography', name: 'Geography', levels: ['country', 'state', 'city'].map(field) }
const config: BIConfig = {
    ...DEFAULT_BI_CONFIG,
    source: { table: 'events' },
    chartType: ChartDisplayType.ActionsTable,
    rows: [field('country')],
    values: [{ field: field('event'), aggregation: 'count' }],
    hierarchies: [geography],
}

function worksheet(config: BIConfig): BIVisualizationNode {
    return { ...buildBIQuery(config)!.node, kind: NodeKind.BIVisualizationNode, config }
}

it.each(['rows', 'columns'] as const)(
    'drills through successive %s levels while retaining parent filters and query context',
    (shelf) => {
        const node = worksheet({ ...config, rows: [], [shelf]: [field('country')] })
        node.source.filters = { dateRange: { date_from: '-30d' }, filterTestAccounts: true }
        node.source.variables = { test: { variableId: 'test', code_name: 'test', value: 'example' } }
        const dimension = getBIResultDimensions(node.config)[0]
        const selection = getBIDrillSelection(node.config, { [dimension.column]: "Example's country" })
        const [drill] = getBIHierarchyDrills(node, selection)
        expect(drill.next.name).toBe('state')
        expect(drill.worksheet.config[shelf]).toEqual([{ ...field('state'), id: 'country' }])
        expect(drill.worksheet.source.query).toContain("properties.country = 'Example\\'s country'")
        expect(drill.worksheet.source.filters).toEqual(node.source.filters)
        expect(drill.worksheet.source.variables).toEqual(node.source.variables)
        const nextDimension = getBIResultDimensions(drill.worksheet.config)[0]
        const [city] = getBIHierarchyDrills(
            drill.worksheet,
            getBIDrillSelection(drill.worksheet.config, { [nextDimension.column]: null })
        )
        expect(city.next.name).toBe('city')
        expect(city.worksheet.source.query).toContain('properties.state IS NULL')
        expect(city.worksheet.source.query).toContain("properties.country = 'Example\\'s country'")
        expect(parseBIEditorState(BIEditorView.BI, city.worksheet.config)?.config.hierarchies).toEqual([geography])
    }
)

it('preserves OR filter semantics, other dimensions, and measure calculations', () => {
    const market = field('market')
    const channel = field('channel')
    const node = worksheet({
        ...config,
        columns: [channel],
        filters: [{ field: market, operator: 'equals', value: 'example' }],
        rowFilterGroup: { operator: 'OR', filters: [market.id], groups: [] },
        values: [{ ...config.values[0], tableCalculation: { type: 'percent_of_total' } }],
        topN: { fieldId: 'country', count: 5, measureIndex: 0, includeOther: false },
    })
    const [dimension] = getBIResultDimensions(node.config)
    const [drill] = getBIHierarchyDrills(node, getBIDrillSelection(node.config, { [dimension.column]: 'Example' }))
    expect(drill.worksheet.config.columns).toEqual([channel])
    expect(drill.worksheet.config.values).toEqual(node.config.values)
    expect(drill.worksheet.config.rowFilterGroup?.operator).toBe('AND')
    expect(drill.worksheet.config.rowFilterGroup?.groups[0].operator).toBe('OR')
    expect(drill.worksheet.config.topN).toBeUndefined()
})

it('does not offer another level for grand totals, leaf fields, or a level already on a shelf', () => {
    for (const rows of [[field('city')], [field('country'), field('state')]]) {
        const node = worksheet({ ...config, rows })
        const [dimension] = getBIResultDimensions(node.config)
        expect(getBIHierarchyDrills(node, getBIDrillSelection(node.config, { [dimension.column]: 'Example' }))).toEqual(
            []
        )
    }
    const node = worksheet(config)
    expect(getBIHierarchyDrills(node, getBIDrillSelection(config, {}))).toEqual([])
})

it('rejects invalid definitions and malformed persisted levels', () => {
    expect(hierarchyError({ ...geography, levels: [field('country'), field('country')] }, config)).toBeTruthy()
    expect(
        hierarchyError(
            { ...geography, levels: [field('country'), { ...field('state'), source: { table: 'other' } }] },
            config
        )
    ).toBeTruthy()
    expect(
        hierarchyError(
            {
                ...geography,
                levels: [
                    field('country'),
                    {
                        ...field('state'),
                        localDefinition: { kind: 'expression', expression: 'count()', aggregate: true },
                    },
                ],
            },
            config
        )
    ).toBeTruthy()
    expect(
        parseBIEditorState(BIEditorView.BI, {
            ...config,
            hierarchies: [{ ...geography, levels: [null, field('state')] }],
        })
    ).toBeNull()
})

it('reverses successive drills without dropping original or newly added user filters and keeps formatting', () => {
    const market = field('market')
    const initial = worksheet({
        ...config,
        filters: [{ field: market, operator: 'equals', value: 'retail' }],
        rowFilterGroup: { operator: 'OR', filters: ['market'], groups: [] },
    })
    initial.chartSettings = {
        ...initial.chartSettings,
        legendPosition: 'bottom',
        leftYAxisSettings: { label: 'Orders', showGridLines: false },
    }
    const [state] = getBIHierarchyDrills(
        initial,
        getBIDrillSelection(initial.config, { 'properties.country': 'Example' })
    )
    const [city] = getBIHierarchyDrills(
        state.worksheet,
        getBIDrillSelection(state.worksheet.config, { 'properties.state': null })
    )
    const changed = {
        ...city.worksheet,
        config: {
            ...city.worksheet.config,
            filters: [
                ...city.worksheet.config.filters,
                { field: field('channel'), operator: 'equals' as const, value: 'direct' },
            ],
        },
    }
    const parent = getBIHierarchyParent(changed)!
    expect(parent.config.rows[0].name).toBe('state')
    expect(parent.source.query).toContain("properties.country = 'Example'")
    expect(parent.source.query).not.toContain('properties.state IS NULL')
    expect(parent.source.query).toContain("properties.channel = 'direct'")
    expect(parent.chartSettings?.leftYAxisSettings).toMatchObject({ label: 'Orders', showGridLines: false })
    const root = getBIHierarchyParent(parent)!
    expect(root.config.rows[0].name).toBe('country')
    expect(root.source.query).not.toContain("properties.country = 'Example'")
    expect(root.source.query).toContain("properties.market = 'retail'")
    expect(root.source.query).toContain("properties.channel = 'direct'")
    expect(getBIHierarchyParent(root)).toBeNull()
    expect(getBIHierarchyParent({ ...parent, config: { ...parent.config, rows: [field('unrelated')] } })).toBeNull()
    expect(parseBIEditorState(BIEditorView.BI, JSON.stringify(parent.config))?.config.hierarchyDrillPath).toEqual(
        parent.config.hierarchyDrillPath
    )
})
