import { BIConfig, BIField, BILocalFieldDefinition } from '~/queries/schema/schema-business-intelligence'
import { escapeHogQLString } from '~/queries/utils'

export function localFieldError(definition: BILocalFieldDefinition): string | undefined {
    if (!definition || typeof definition.expression !== 'string' || !definition.expression.trim()) {
        return 'Choose a source field'
    }
    if (definition.kind === 'expression') {
        return typeof definition.aggregate === 'boolean' ? undefined : 'Choose a dimension or measure'
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
        (!definition.preserveUngrouped && !definition.other.trim()) ||
        (definition.preserveUngrouped !== undefined && typeof definition.preserveUngrouped !== 'boolean')
    ) {
        return 'Add at least one group and a label for other values'
    }
    const used = new Set<string>()
    const names = new Set<string>(definition.preserveUngrouped ? [] : [definition.other])
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

export function inferBICalculatedFieldType(type: string | undefined): BIField['type'] | undefined {
    const base = type?.replace(/^(?:Nullable|LowCardinality)\((.*)\)$/, '$1')
    if (!base) {
        return undefined
    }
    if (/^(?:Nullable|LowCardinality)\(/.test(base)) {
        return inferBICalculatedFieldType(base)
    }
    if (/^U?Int\d+$/.test(base)) {
        return 'integer'
    }
    if (/^(?:Float\d+|Decimal(?:\d+)?\()/.test(base)) {
        return 'float'
    }
    if (base.startsWith('DateTime')) {
        return 'datetime'
    }
    if (/^Date(?:32)?$/.test(base)) {
        return 'date'
    }
    if (base === 'Bool' || base === 'Boolean') {
        return 'boolean'
    }
    return /^(?:String|FixedString\(|UUID|Enum)/.test(base) ? 'string' : undefined
}

export function localFieldExpression(definition: BILocalFieldDefinition): string {
    if (definition.kind === 'expression') {
        return definition.expression.trim()
    }
    if (definition.kind === 'bins') {
        return `(floor(((${definition.expression}) - ${definition.origin}) / ${definition.width}) * ${definition.width} + ${definition.origin})`
    }
    const expression = `(${definition.expression})`
    const cases = definition.groups.flatMap((group) => [
        `toString(${expression}) IN (${group.values.map(escapeHogQLString).join(', ')})`,
        escapeHogQLString(definition.preserveUngrouped ? JSON.stringify(['group', group.name]) : group.name),
    ])
    const fallback = definition.preserveUngrouped
        ? `toJSONString(tuple('value', toString(${expression})))`
        : escapeHogQLString(definition.other)
    return `if(${expression} IS NULL, NULL, multiIf(${[...cases, fallback].join(', ')}))`
}

export function upsertBILocalField(config: BIConfig, field: BIField): BIConfig {
    const matches = (current: BIField): boolean => (current.localFieldId ?? current.id) === field.id
    const replace = (current: BIField): BIField =>
        matches(current)
            ? {
                  ...current,
                  ...field,
                  id: current.id,
                  localFieldId: field.id,
                  dateBucket: ['date', 'datetime'].includes(field.type) ? current.dateBucket : undefined,
                  datePart: ['date', 'datetime'].includes(field.type) ? current.datePart : undefined,
              }
            : current
    return {
        ...config,
        localFields: [...(config.localFields ?? []).filter((current) => current.id !== field.id), field],
        rows: config.rows.map(replace),
        columns: config.columns.map(replace),
        hierarchies: config.hierarchies?.map((hierarchy) => ({ ...hierarchy, levels: hierarchy.levels.map(replace) })),
        values: config.values.map((value) => ({
            ...value,
            field: replace(value.field),
            ...(matches(value.field) && field.localDefinition?.kind === 'expression' && field.localDefinition.aggregate
                ? { aggregation: 'custom' as const, customExpression: field.expression, label: field.name }
                : {}),
        })),
        filters: config.filters.map((filter) => ({ ...filter, field: replace(filter.field) })),
        dateField: config.dateField ? replace(config.dateField) : config.dateField,
    }
}

export function getBILocalFields(config: BIConfig): BIField[] {
    const fields = [...(config.localFields ?? [])]
    for (const value of config.values) {
        const id = value.field.localFieldId ?? value.field.id
        if (
            value.aggregation === 'custom' &&
            value.label &&
            value.customExpression?.trim() &&
            !fields.some((field) => field.id === id)
        ) {
            fields.push({
                ...value.field,
                id,
                name: value.label,
                expression: value.customExpression,
                localDefinition: { kind: 'expression', aggregate: true, expression: value.customExpression },
            })
        }
    }
    return fields
}
