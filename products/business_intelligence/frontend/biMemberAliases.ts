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

export function getBIMemberLabel(config: BIConfig, field: BIField, value: unknown): string {
    return (
        getBIMemberAlias(config, field, value) ??
        (value == null ? '(no value)' : value === '' ? '(empty string)' : String(value))
    )
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
    return [...new Set([...selected, ...values, ...matches])].map((value) => ({
        key: value,
        label: getBIMemberLabel(config, field, value),
    }))
}
