import type { Dayjs } from 'lib/dayjs'

import type { DataTableRow } from '~/queries/nodes/DataTable/dataTableLogic'
import { removeExpressionComment } from '~/queries/nodes/DataTable/utils'

/** Fills a cell whose column has no invented value, so the cell renders as a skeleton bar. */
export const samplePlaceholderColumn = Symbol('sample placeholder')

export interface SampleRowsSource {
    /** One row per invented record, one value per column in `columns`. */
    buildRows: (columns: string[], now: Dayjs) => DataTableRow[]
    dataAttr: string
    /** Columns to hide while the sample shows, for example ones whose actions would act on invented records. */
    hiddenColumns: string[]
}

export interface SampleIds {
    distinctId: string
    personId: string
    eventId: string
}

/** The IDs are obviously invented, so nothing can resolve them to a real person or event. */
export function sampleIds(index: number): SampleIds {
    const suffix = String(index + 1).padStart(12, '0')
    return {
        distinctId: `sample-distinct-id-${index + 1}`,
        personId: `00000000-0000-4000-8000-${suffix}`,
        eventId: `00000000-0000-4000-9000-${suffix}`,
    }
}

export function samplePersonDisplayName(
    email: string,
    ids: SampleIds
): { display_name: string; distinct_id: string; id: string } {
    return { display_name: email, distinct_id: ids.distinctId, id: ids.personId }
}

/** The value of a `properties.<key>` column, or `samplePlaceholderColumn` when the sample has no such property. */
export function samplePropertyValue(key: string, properties: Record<string, unknown>): unknown {
    if (key.startsWith('properties.')) {
        const propertyKey = key.slice('properties.'.length)
        if (Object.hasOwn(properties, propertyKey)) {
            return properties[propertyKey]
        }
    }
    return samplePlaceholderColumn
}

/** `valueFor` gets the column without its `-- comment` suffix. */
export function buildSampleRows<T>(
    samples: T[],
    columns: string[],
    valueFor: (key: string, sample: T, ids: SampleIds) => unknown
): (DataTableRow & { result: unknown[] })[] {
    const keys = columns.map(removeExpressionComment)
    return samples.map((sample, index) => {
        const ids = sampleIds(index)
        return { result: keys.map((key) => valueFor(key, sample, ids)) }
    })
}
