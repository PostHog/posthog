/** Shared Zod helpers for per-widget config validation modules (form parse, API errors, HogQL filters). */
import { z, type ZodError, type ZodType } from 'zod'

import { FilterLogicalOperator, PropertyFilterType, type UniversalFiltersGroup } from '~/types'

import { type WidgetFilterConfigRecord } from '../generated/widget-configs.zod'

/** Converts persisted widget `config.widgetFilters` into a HogQL/universal filter group. */
export function buildFilterGroupFromWidgetFilters(
    widgetFilters: WidgetFilterConfigRecord | undefined
): UniversalFiltersGroup | undefined {
    const selections = widgetFilters ? Object.values(widgetFilters) : []
    if (selections.length === 0) {
        return undefined
    }

    const filtersFromWidgetFilters = selections.map((entry) => {
        const filterValue = entry.value === null ? undefined : Array.isArray(entry.value) ? entry.value : [entry.value]

        return {
            type: PropertyFilterType.Event,
            key: entry.propertyName,
            operator: entry.operator,
            ...(filterValue !== undefined && { value: filterValue }),
        }
    })

    return {
        type: FilterLogicalOperator.And,
        values: [
            {
                type: FilterLogicalOperator.And,
                values: filtersFromWidgetFilters,
            },
        ],
    } as UniversalFiltersGroup
}

export function fieldErrorsFromZodError<TField extends string>(error: ZodError): Partial<Record<TField, string>> {
    const { fieldErrors } = z.flattenError(error)

    return Object.fromEntries(
        (Object.entries(fieldErrors) as [string, string[]][]).flatMap(([field, messages]) =>
            messages.length > 0 ? [[field, messages[0]]] : []
        )
    ) as Partial<Record<TField, string>>
}

export function parseWidgetConfig<T>(configSchema: ZodType<T>, config: Record<string, unknown>): T {
    const parsed = configSchema.safeParse(config)
    return parsed.success ? parsed.data : configSchema.parse({})
}

export type WidgetListFormInput = {
    limit: number
    orderBy: string
    dateRange: { date_from?: string | null } | null
    filterTestAccounts: boolean | null
}
