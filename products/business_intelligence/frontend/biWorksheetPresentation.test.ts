import { BIConfig, BIField, BIFilter, BIVisualizationNode } from '~/queries/schema/schema-business-intelligence'
import { NodeKind } from '~/queries/schema/schema-general'

import { getBIDrillSelection } from './biDrilldown'
import { BIEditorView, buildBIQuery, DEFAULT_BI_CONFIG, parseBIEditorState } from './biEditorTypes'
import { describeBIFilter, getBIActiveFilterSummary, getBIFilterLabel } from './biFilterSummary'
import { createBIMemberFormatter, getBIMemberAlias, getBIMemberLabel, getBIMemberOptions } from './biMemberAliases'
import { buildBISourcePreview } from './biSourcePreview'

const country: BIField = {
    id: 'country',
    name: 'Country',
    expression: 'country',
    type: 'string',
    source: { table: 'example_orders', connectionId: 'example-connection' },
}
const config: BIConfig = { ...DEFAULT_BI_CONFIG, source: country.source, rows: [country] }

it.each<[BIFilter['operator'], string, string | undefined, string]>([
    ['equals', 'US', undefined, 'United States'],
    ['not_equals', 'US', undefined, 'Not United States'],
    ['contains', 'US', undefined, 'Contains US'],
    ['greater_than', '10', undefined, '> 10'],
    ['less_than', '20', undefined, '< 20'],
    ['between', '10', '20', '10 to 20'],
])(
    'describes %s operands without replacing substrings or bounds with member aliases',
    (operator, value, valueTo, expected) => {
        const field = ['greater_than', 'less_than', 'between'].includes(operator)
            ? { ...country, type: 'integer' as const }
            : country
        const aliased: BIConfig = {
            ...config,
            memberAliases: [
                {
                    field,
                    aliases: [
                        { value: 'US', label: 'United States' },
                        { value: '10', label: 'Ten' },
                        { value: '20', label: 'Twenty' },
                    ],
                },
            ],
        }
        expect(describeBIFilter({ field, operator, value, valueTo }, aliased)).toBe(expected)
    }
)

it('renames filters independently and describes the executed nested conditions without inactive filters', () => {
    const filtered: BIConfig = {
        ...config,
        filters: [
            { field: country, label: ' Sales territory ', operator: 'in', values: ['north', ''], value: '' },
            { field: { ...country, id: 'second' }, label: 'Alternative', operator: 'equals', value: 'west' },
            {
                field: { ...country, id: 'disabled' },
                label: 'Disabled',
                operator: 'equals',
                value: 'east',
                enabled: false,
            },
            { field: { ...country, id: 'noop' }, operator: 'in', values: [], value: '' },
        ],
        rowFilterGroup: {
            operator: 'AND',
            filters: ['disabled', 'noop'],
            groups: [{ operator: 'OR', filters: ['country', 'second'], groups: [] }],
        },
        memberAliases: [{ field: country, aliases: [{ value: 'north', label: 'Northern area' }] }],
        resultFilters: [
            { id: 'count', label: 'Minimum orders', measureIndex: 0, operator: 'greater_than', value: '2' },
        ],
    }
    const summary = getBIActiveFilterSummary(filtered)
    expect(summary.rows).toContain('Sales territory: is one of "Northern area", "(empty string)"')
    expect(summary.rows).toContain(' OR ')
    expect(summary.rows).not.toContain('Disabled')
    expect(summary.rows).not.toContain('All values')
    expect(summary.results).toContain('Minimum orders')
    const parsed = parseBIEditorState(BIEditorView.BI, JSON.stringify(filtered))!.config
    expect(parsed.filters[0].label).toBe('Sales territory')
    const withoutLabels = { ...filtered, filters: filtered.filters.map(({ label, ...filter }) => filter) }
    expect(buildBIQuery(filtered)?.query).toEqual(buildBIQuery(withoutLabels)?.query)
    expect(getBIFilterLabel({ ...filtered.filters[0], label: '   ' })).toBe('Country')
    expect(country.name).toBe('Country')
})

it('preserves distinct raw identity for duplicate aliases, null, empty and numeric-looking members', () => {
    const aliased: BIConfig = {
        ...config,
        memberAliases: [
            {
                field: country,
                aliases: [
                    { value: '01', label: 'One' },
                    { value: '1', label: 'One' },
                    { value: null, label: 'Missing' },
                    { value: '', label: 'Blank' },
                ],
            },
        ],
    }
    expect(getBIMemberLabel(aliased, country, '01')).toBe('One')
    expect(getBIMemberLabel(aliased, country, '1')).toBe('One')
    expect(getBIMemberLabel(aliased, country, null)).toBe('Missing')
    expect(getBIMemberOptions(aliased, country, [], ['unlisted'], 'one')).toEqual([
        { key: 'unlisted', label: 'unlisted' },
        { key: '01', label: 'One' },
        { key: '1', label: 'One' },
    ])
    expect(getBIMemberLabel(aliased, country, '')).toBe('Blank')
    expect(getBIMemberLabel(aliased, country, 'new')).toBe('new')
    expect(getBIMemberAlias(aliased, { ...country, source: { table: 'other' } }, '01')).toBeUndefined()
    expect(buildBIQuery(aliased)?.query).toEqual(buildBIQuery(config)?.query)
    const selection = getBIDrillSelection(aliased, { country: '01' })
    expect(selection.filters[0].value).toBe('01')
    expect(selection.labels[0].value).toBe('One')
    expect(parseBIEditorState(BIEditorView.BI, JSON.stringify(aliased))?.config.memberAliases).toEqual(
        aliased.memberAliases
    )
    expect(
        parseBIEditorState(BIEditorView.BI, {
            ...aliased,
            memberAliases: [{ field: country, aliases: [{ value: 'x', label: 42 }] }],
        })
    ).toBeNull()
})

it.each(['localFields', 'hierarchies', 'memberAliases', 'hierarchyDrillPath'] as const)(
    'restores a nullable %s definition as absent without discarding the worksheet',
    (definition) => {
        const restored = parseBIEditorState(BIEditorView.BI, JSON.stringify({ ...config, [definition]: null }))
        expect(restored?.config.source).toEqual(config.source)
        expect(restored?.config.rows).toEqual(config.rows)
        expect(restored?.config[definition]).toBeUndefined()
        expect(buildBIQuery(restored!.config)?.query).toEqual(buildBIQuery(config)?.query)
    }
)

it('previews a blank source, separates all rows from worksheet filters and bounds sample size without mutating it', () => {
    const filtered: BIConfig = {
        ...config,
        rows: [],
        filters: [{ field: country, operator: 'equals', value: 'north' }],
        resultFilters: [{ id: 'aggregate', measureIndex: 0, operator: 'greater_than', value: '9' }],
        dateRange: { date_from: '-30d' },
    }
    const worksheet: BIVisualizationNode = {
        kind: NodeKind.BIVisualizationNode,
        config: filtered,
        source: {
            kind: NodeKind.HogQLQuery,
            query: '',
            connectionId: country.source.connectionId,
            variables: { example: { variableId: 'example', code_name: 'example', value: 'test' } },
            filters: { dateRange: filtered.dateRange },
        },
    }
    const before = JSON.stringify(worksheet)
    const all = buildBISourcePreview(worksheet, false, 1000)!
    const matching = buildBISourcePreview(worksheet, true, 2000)!
    expect(all.source.query).toContain('SELECT *')
    expect(all.source.query).not.toContain("country = 'north'")
    expect(matching.source.query).toContain("country = 'north'")
    expect(matching.source.query).not.toContain('HAVING')
    expect(matching.source.query).toContain('LIMIT 2000')
    expect(matching.source.filters?.dateRange).toEqual(filtered.dateRange)
    expect(all.source.filters?.dateRange?.date_from).toBe('all')
    expect(matching.source.connectionId).toBe(country.source.connectionId)
    expect(matching.source.variables).toEqual(worksheet.source.variables)
    expect(buildBISourcePreview(worksheet, false, 999999)?.source.query).toContain('LIMIT 10000')
    expect(JSON.stringify(worksheet)).toBe(before)
})

it('formats preserved groups without saved aliases while leaving ordinary numeric axes to the chart', () => {
    const grouped: BIField = {
        ...country,
        localDefinition: {
            kind: 'groups',
            expression: 'country',
            other: 'Other',
            groups: [{ name: 'Combined', values: ['north', 'east'] }],
            preserveUngrouped: true,
        },
    }
    const format = createBIMemberFormatter(config, grouped)!
    expect(format(JSON.stringify(['group', 'Combined']))).toBe('Combined')
    expect(format(JSON.stringify(['value', 'Combined']))).toBe('Combined (ungrouped)')
    expect(format(JSON.stringify(['value', 'west']))).toBe('west')
    expect(format(null)).toBe('(no value)')
    expect(createBIMemberFormatter(config, { ...country, type: 'integer' })).toBeUndefined()
})

it('describes thousands of selected aliases with linear member reads', () => {
    let reads = 0
    const aliases = Array.from({ length: 2000 }, (_, index) => ({
        get value(): string {
            reads++
            return `value-${index}`
        },
        label: `Label ${index}`,
    }))
    const summary = getBIActiveFilterSummary({
        ...config,
        memberAliases: [{ field: country, aliases }],
        filters: [
            {
                field: country,
                operator: 'in',
                value: '',
                values: Array.from({ length: 2000 }, (_, index) => `value-${index}`),
            },
        ],
    })
    expect(summary.rows).toContain('"Label 0", "Label 1"')
    expect(summary.rows).toContain('"Label 1999"')
    expect(reads).toBeLessThan(aliases.length * 4)
})
