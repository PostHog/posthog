import { BIConfig, BIField } from '~/queries/schema/schema-business-intelligence'

export function biMemberFieldKey(field: BIField): string {
    return JSON.stringify([
        field.source.connectionId ?? null,
        field.source.table,
        field.localFieldId ?? (field.localDefinition ? field.id : field.expression.trim()),
        field.dateBucket ?? null,
        field.datePart ?? null,
    ])
}

export function getBIMemberAlias(config: BIConfig, field: BIField, value: unknown): string | undefined {
    const raw = value == null ? null : String(value)
    return config.memberAliases
        ?.find((entry) => biMemberFieldKey(entry.field) === biMemberFieldKey(field))
        ?.aliases.find((alias) => alias.value === raw)?.label
}

function defaultMemberLabel(field: BIField, value: unknown): string {
    const definition = field.localDefinition
    if (typeof value === 'string' && definition?.kind === 'groups' && definition.preserveUngrouped) {
        try {
            const decoded: unknown = JSON.parse(value)
            if (Array.isArray(decoded) && decoded.length === 2 && typeof decoded[1] === 'string') {
                if (decoded[0] === 'group') {
                    return decoded[1]
                }
                if (decoded[0] === 'value') {
                    return definition.groups.some((group) => group.name === decoded[1])
                        ? `${decoded[1]} (ungrouped)`
                        : decoded[1] === ''
                          ? '(empty string)'
                          : decoded[1]
                }
            }
        } catch {
            // Older saved results may still contain unencoded member labels.
        }
    }
    return value == null ? '(no value)' : value === '' ? '(empty string)' : String(value)
}

export function createBIMemberDisplayLookup(config: BIConfig): (field: BIField, value: unknown) => string | undefined {
    const aliases = new Map<string, Map<string | null, string>>()
    for (const entry of config.memberAliases ?? []) {
        const key = biMemberFieldKey(entry.field)
        if (!aliases.has(key)) {
            aliases.set(key, new Map(entry.aliases.map(({ value, label }) => [value, label])))
        }
    }
    const fieldAliases = new Map<BIField, Map<string | null, string> | undefined>()
    return (field, value) => {
        if (!fieldAliases.has(field)) {
            fieldAliases.set(field, aliases.get(biMemberFieldKey(field)))
        }
        return (
            fieldAliases.get(field)?.get(value == null ? null : String(value)) ??
            (field.localDefinition?.kind === 'groups' && field.localDefinition.preserveUngrouped
                ? defaultMemberLabel(field, value)
                : undefined)
        )
    }
}

export function createBIMemberLabelLookup(config: BIConfig): (field: BIField, value: unknown) => string {
    const display = createBIMemberDisplayLookup(config)
    return (field, value) => display(field, value) ?? defaultMemberLabel(field, value)
}

export function createBIMemberFormatter(config: BIConfig, field: BIField): ((value: unknown) => string) | undefined {
    if (
        !(field.localDefinition?.kind === 'groups' && field.localDefinition.preserveUngrouped) &&
        !config.memberAliases?.some((entry) => biMemberFieldKey(entry.field) === biMemberFieldKey(field))
    ) {
        return undefined
    }
    const label = createBIMemberLabelLookup(config)
    return (value) => label(field, value)
}

export function getBIMemberLabel(config: BIConfig, field: BIField, value: unknown): string {
    return getBIMemberAlias(config, field, value) ?? defaultMemberLabel(field, value)
}

export function getBIMemberOptions(
    config: BIConfig,
    field: BIField,
    values: string[],
    selected: string[],
    search: string
): { key: string; label: string }[] {
    const aliases = config.memberAliases?.find((entry) => biMemberFieldKey(entry.field) === biMemberFieldKey(field))
    const matches =
        aliases?.aliases.flatMap(({ value, label }) =>
            value !== null && label.toLowerCase().includes(search.toLowerCase()) ? [value] : []
        ) ?? []
    const label = createBIMemberLabelLookup(config)
    return [...new Set([...selected, ...values, ...matches])].map((value) => ({
        key: value,
        label: label(field, value),
    }))
}
