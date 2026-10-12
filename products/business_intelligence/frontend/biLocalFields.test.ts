import { BIField, BILocalFieldDefinition } from '~/queries/schema/schema-business-intelligence'

import { BIEditorView, buildBIQuery, DEFAULT_BI_CONFIG, parseBIEditorState } from './biEditorTypes'
import { localFieldError, localFieldExpression, upsertBILocalField } from './biLocalFields'

it.each<BILocalFieldDefinition>([
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
