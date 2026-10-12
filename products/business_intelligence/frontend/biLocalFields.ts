import { BIConfig, BIField, BILocalFieldDefinition } from '~/queries/schema/schema-business-intelligence'
import { escapeHogQLString } from '~/queries/utils'

export function localFieldError(definition: BILocalFieldDefinition): string | undefined {
    if (!definition || typeof definition.expression !== 'string' || !definition.expression.trim()) {
        return 'Choose a source field'
    }
    if (definition.kind === 'bins') {
        return Number.isFinite(definition.width) && definition.width > 0 && Number.isFinite(definition.origin)
            ? undefined
            : 'Use a positive bin width and a finite starting point'
    }
    if (
        definition.kind !== 'groups' ||
        !Array.isArray(definition.groups) ||
        !definition.groups.length ||
        definition.groups.length > 100 ||
        typeof definition.other !== 'string' ||
        !definition.other.trim()
    ) {
        return 'Add at least one group and a label for other values'
    }
    const used = new Set<string>()
    const names = new Set<string>([definition.other])
    for (const group of definition.groups) {
        if (
            !group ||
            typeof group.name !== 'string' ||
            !group.name.trim() ||
            !Array.isArray(group.values) ||
            !group.values.length ||
            group.values.length > 10000 ||
            !group.values.every((value) => typeof value === 'string')
        ) {
            return 'Give every group a name and at least one value'
        }
        if (names.has(group.name)) {
            return 'Group names and the other-values label must be distinct'
        }
        names.add(group.name)
        for (const value of group.values) {
            if (used.has(value)) {
                return 'Each value can belong to only one group'
            }
            used.add(value)
        }
    }
}

export function localFieldExpression(definition: BILocalFieldDefinition): string {
    if (definition.kind === 'bins') {
        return `(floor(((${definition.expression}) - ${definition.origin}) / ${definition.width}) * ${definition.width} + ${definition.origin})`
    }
    const expression = `(${definition.expression})`
    const cases = definition.groups.flatMap((group) => [
        `toString(${expression}) IN (${group.values.map(escapeHogQLString).join(', ')})`,
        escapeHogQLString(group.name),
    ])
    return `if(${expression} IS NULL, NULL, multiIf(${[...cases, escapeHogQLString(definition.other)].join(', ')}))`
}

export function upsertBILocalField(config: BIConfig, field: BIField): BIConfig {
    const replace = (current: BIField): BIField => (current.id === field.id ? field : current)
    return {
        ...config,
        localFields: [...(config.localFields ?? []).filter((current) => current.id !== field.id), field],
        rows: config.rows.map(replace),
        columns: config.columns.map(replace),
        values: config.values.map((value) => ({ ...value, field: replace(value.field) })),
        filters: config.filters.map((filter) => ({ ...filter, field: replace(filter.field) })),
    }
}
