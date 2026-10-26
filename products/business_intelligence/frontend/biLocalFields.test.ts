import { BIField, BILocalFieldDefinition } from '~/queries/schema/schema-business-intelligence'
import { NodeKind } from '~/queries/schema/schema-general'

import { getBIDrillQueries, getBIDrillSelection } from './biDrilldown'
import { BIEditorView, buildBIQuery, DEFAULT_BI_CONFIG, parseBIEditorState } from './biEditorTypes'
import { getBIResultDimensions } from './biEditorTypes'
import { inferBICalculatedFieldType, localFieldError, localFieldExpression, upsertBILocalField } from './biLocalFields'
import { getBIMemberLabel } from './biMemberAliases'

it.each([
    ['Nullable(Int64)', 'integer'],
    ['LowCardinality(Nullable(String))', 'string'],
    ['Decimal(18, 2)', 'float'],
    ["DateTime64(3, 'UTC')", 'datetime'],
    ['Date32', 'date'],
    ['Bool', 'boolean'],
    ['Array(String)', undefined],
    [undefined, undefined],
])('infers the calculated field type of %s', (type, expected) => {
    expect(inferBICalculatedFieldType(type)).toBe(expected)
})

it.each<BILocalFieldDefinition>([
    { kind: 'expression', expression: "coalesce(properties.plan, 'Unknown')", aggregate: false },
    { kind: 'expression', expression: 'sum(properties.amount)', aggregate: true },
    {
        kind: 'groups',
        expression: 'properties.country',
        groups: [{ name: "Europe's region", values: ['France', "Cote d'Ivoire"] }],
        other: 'Rest',
    },
    { kind: 'bins', expression: 'properties.size', width: 10, origin: -5 },
])('persists $kind locally and updates the expression on every shelf', (definition) => {
    const field: BIField = {
        id: 'local',
        name: 'Region',
        source: { table: 'events' },
        type: definition.kind === 'bins' ? 'float' : 'string',
        expression: 'old',
        localDefinition: definition,
    }
    const config = {
        ...DEFAULT_BI_CONFIG,
        source: field.source,
        rows: [field],
        columns: [field],
        values: [{ field, aggregation: 'count' as const }],
        filters: [{ field, operator: 'is_set' as const, value: '' }],
    }
    const updated = upsertBILocalField(config, { ...field, expression: localFieldExpression(definition) })
    const parsed = parseBIEditorState(BIEditorView.BI, updated)!.config
    expect(parsed.localFields?.[0].localDefinition).toEqual(definition)
    expect(
        [parsed.rows[0], parsed.columns[0], parsed.values[0].field, parsed.filters[0].field].map(
            (field) => field.expression
        )
    ).toEqual(Array(4).fill(localFieldExpression(definition)))
    expect(buildBIQuery(parsed)?.query).not.toContain('old')
    if (definition.kind === 'expression' && !definition.aggregate) {
        const node = { ...buildBIQuery(config)!.node, kind: NodeKind.BIVisualizationNode as const, config }
        const record = Object.fromEntries(getBIResultDimensions(config).map(({ column }) => [column, 'Selected']))
        const drilled = getBIDrillQueries(node, getBIDrillSelection(config, record))!.worksheet!
        const edited = upsertBILocalField(drilled.config, { ...field, expression: localFieldExpression(definition) })
        expect(
            edited.filters.filter(({ field }) => field.id.startsWith('drill:')).map(({ field }) => field.expression)
        ).toEqual(Array(2).fill(localFieldExpression(definition)))
    }

    if (definition.kind === 'groups') {
        expect(buildBIQuery(parsed)?.query).toContain("'Cote d\\'Ivoire'")
        expect(buildBIQuery(parsed)?.query).toContain('IS NULL, NULL')
    }
})

it.each([
    { kind: 'bins', expression: 'size', width: 0, origin: 0 },
    { kind: 'bins', expression: 'size', width: 10, origin: Infinity },
    {
        kind: 'groups',
        expression: 'country',
        groups: [
            { name: 'A', values: ['US'] },
            { name: 'B', values: ['US'] },
        ],
        other: 'Other',
    },
] as BILocalFieldDefinition[])('rejects invalid or ambiguous local definitions: %j', (definition) => {
    expect(localFieldError(definition)).toBeTruthy()
})

it('can preserve ungrouped members including null and empty, while legacy groups keep Other', () => {
    const definition: BILocalFieldDefinition = {
        kind: 'groups',
        expression: 'country',
        groups: [{ name: 'Combined', values: ['A', 'B'] }],
        other: 'Other',
    }
    const preserved = { ...definition, preserveUngrouped: true }
    expect(localFieldError(preserved)).toBeUndefined()
    expect(localFieldExpression(preserved)).toContain('(country) IS NULL, NULL')
    expect(localFieldExpression(preserved)).toContain(`toJSONString(tuple('value', toString((country))))`)
    expect(localFieldExpression(preserved)).toContain(JSON.stringify(['group', 'Combined']))
    const field: BIField = {
        id: 'group',
        name: 'Group',
        expression: localFieldExpression(preserved),
        type: 'string',
        source: { table: 'events' },
        localDefinition: preserved,
    }
    expect(getBIMemberLabel(DEFAULT_BI_CONFIG, field, JSON.stringify(['group', 'Combined']))).toBe('Combined')
    expect(getBIMemberLabel(DEFAULT_BI_CONFIG, field, JSON.stringify(['value', 'Combined']))).toBe(
        'Combined (ungrouped)'
    )
    expect(getBIMemberLabel(DEFAULT_BI_CONFIG, field, JSON.stringify(['value', '']))).toBe('(empty string)')
    expect(localFieldExpression(definition)).toContain("'Other'))")
    expect(localFieldError({ ...preserved, other: '' })).toBeUndefined()
    expect(localFieldError({ ...definition, other: '' })).toBeTruthy()
})
