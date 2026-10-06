import { BIConfig, BIDataSource, BIField } from '~/queries/schema/schema-business-intelligence'
import { DateRange, HogQLFilters, HogQLQuery } from '~/queries/schema/schema-general'
import { escapeHogQLString } from '~/queries/utils'

const NATIVE_DATE_FIELDS: Record<string, string> = {
    events: 'timestamp',
    ai_events: 'timestamp',
    sessions: '$start_timestamp',
    persons: 'created_at',
    groups: 'created_at',
    logs: 'timestamp',
    traces: 'timestamp',
}

export function getBIDateField(config: BIConfig): BIField | null {
    if (config.dateField !== undefined) {
        return config.dateField
    }
    const source = config.source
    const expression = source && !source.connectionId ? NATIVE_DATE_FIELDS[source.table] : undefined
    return source && expression
        ? { id: `bi-date:${source.table}:${expression}`, name: expression, expression, type: 'datetime', source }
        : null
}

export function usesNativeBIFilters(source: BIDataSource | null): boolean {
    return !!source && !source.connectionId && !!NATIVE_DATE_FIELDS[source.table]
}

export function normalizeBIDates(config: BIConfig): BIConfig {
    if (config.dateRange !== undefined) {
        return config
    }
    const legacy = config.filters.find(
        (filter) => filter.field.id.startsWith('bi-default:') && filter.operator === 'last_7_days'
    )
    return legacy
        ? {
              ...config,
              dateField: legacy.field,
              dateRange: { date_from: legacy.enabled === false ? 'all' : '-7d' },
              filters: config.filters.filter((filter) => filter !== legacy),
          }
        : config
}

export function getBIFiltersPlaceholder(config: BIConfig): string {
    const dateField = getBIDateField(config)
    if (usesNativeBIFilters(config.source)) {
        return dateField?.expression === NATIVE_DATE_FIELDS[config.source!.table]
            ? '{filters}'
            : `{filters.native(${dateField?.expression || 'null'})}`
    }
    const bindings = new Map<string, string>([['timestamp', dateField?.expression || 'null']])
    const ambiguous = new Set<string>()
    for (const field of [
        ...config.rows,
        ...config.columns,
        ...config.values.map((value) => value.field),
        ...config.filters.map((filter) => filter.field),
    ]) {
        const propertyKey = field.name.replace(/^(?:.*\.)?(?:properties|person_properties)\./, '')
        for (const key of new Set([field.name, propertyKey])) {
            if (!key || key === 'timestamp' || !field.expression.trim() || ambiguous.has(key)) {
                continue
            }
            if (bindings.has(key) && bindings.get(key) !== field.expression) {
                bindings.delete(key)
                ambiguous.add(key)
            } else {
                bindings.set(key, field.expression)
            }
        }
    }
    return `{filters(${[...bindings].map(([key, expression]) => `(${expression}) AS ${escapeHogQLString(key)}`).join(', ')})}`
}

export function getBIQueryFilters(config: BIConfig, filters?: HogQLFilters): HogQLFilters {
    return { ...filters, dateRange: config.dateRange ?? { date_from: 'all' }, compareFilter: config.compareFilter }
}

export function mergeBIQuerySource(current: HogQLQuery, generated: HogQLQuery): HogQLQuery {
    return { ...current, ...generated, filters: { ...current.filters, ...generated.filters } }
}

export function applyBIDateRange(config: BIConfig, dateRange: DateRange | undefined): BIConfig {
    if (
        !dateRange ||
        ((config.dateRange?.date_from ?? 'all') === (dateRange.date_from ?? 'all') &&
            (config.dateRange?.date_to ?? null) === (dateRange.date_to ?? null) &&
            !!config.dateRange?.explicitDate === !!dateRange.explicitDate)
    ) {
        return config
    }
    return { ...config, dateRange }
}
