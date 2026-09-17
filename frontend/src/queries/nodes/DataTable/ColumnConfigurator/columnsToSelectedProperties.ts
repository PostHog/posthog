import {
    SelectedProperties,
    TaxonomicFilterGroupType,
    TaxonomicFilterValue,
} from 'lib/components/TaxonomicFilter/types'

import { trimQuotes } from '~/queries/utils'

import { removeExpressionComment } from '../utils'

/** A simple identifier, so every converter returns it unescaped and the prefix is recoverable. */
const PROBE_KEY = 'probe'

export type ColumnToHogQL = (groupType: TaxonomicFilterGroupType, value: TaxonomicFilterValue) => string | null

/** The text a converter puts in front of a property key, e.g. `properties.`. Null when the group has no prefix to strip. */
function columnPrefixForGroup(groupType: TaxonomicFilterGroupType, toHogQL: ColumnToHogQL): string | null {
    const probeColumn = toHogQL(groupType, PROBE_KEY)
    if (!probeColumn || probeColumn === PROBE_KEY || !probeColumn.endsWith(PROBE_KEY)) {
        return null
    }
    return probeColumn.slice(0, -PROBE_KEY.length)
}

/**
 * Invert the columns of a data table back into the taxonomic values that produced them, so the picker
 * can mark a property that is already a column. Every candidate key is confirmed by running it back
 * through `toHogQL`, which keeps identifier escaping in one place and drops keys that do not match.
 */
export function columnsToSelectedProperties({
    columns,
    taxonomicGroupTypes,
    toHogQL,
    implicitPrefixGroupType,
}: {
    columns: string[]
    taxonomicGroupTypes: TaxonomicFilterGroupType[]
    toHogQL: ColumnToHogQL
    /** Group whose prefix the table's own namespace makes optional — a sessions table selects `$is_bounce` as well as `session.$is_bounce`. */
    implicitPrefixGroupType?: TaxonomicFilterGroupType
}): SelectedProperties {
    const bareColumns = columns.map((column) => removeExpressionComment(column).trim())
    const selectedProperties: SelectedProperties = {}

    for (const groupType of taxonomicGroupTypes) {
        const prefix = columnPrefixForGroup(groupType, toHogQL)
        if (prefix === null) {
            continue
        }
        const values: string[] = []
        for (const column of bareColumns) {
            const key = trimQuotes(column.startsWith(prefix) ? column.slice(prefix.length) : column)
            const rebuilt = toHogQL(groupType, key)
            if (rebuilt === column || (groupType === implicitPrefixGroupType && rebuilt === `${prefix}${column}`)) {
                values.push(key)
            }
        }
        if (values.length > 0) {
            selectedProperties[groupType] = values
        }
    }

    return selectedProperties
}
