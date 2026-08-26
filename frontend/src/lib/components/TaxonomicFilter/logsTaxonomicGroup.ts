/**
 * The Logs taxonomic group's option list and value lookups, defined once and consumed by both the
 * legacy `taxonomicFilterLogic` group and the rebuild's `buildTaxonomicGroups` — the two variants
 * must offer the same log columns, and a shared definition is the only guard against drift.
 */
import { combineUrl } from 'kea-router'

export interface LogsTaxonomicOption {
    key: string
    name: string
    propertyFilterType: 'log'
}

// `service_name` deliberately carries the `log` filter type: the ingestion matcher and the query
// builder resolve it to the first-class column, the same filter the logs facet rail writes. The
// log-attribute group offers a same-named key holding namespace/container values the column never
// equals, so this option is the one a service filter must come from.
export const LOGS_TAXONOMIC_OPTIONS: LogsTaxonomicOption[] = [
    { key: 'message', name: 'message', propertyFilterType: 'log' },
    { key: 'severity_level', name: 'severity_level', propertyFilterType: 'log' },
    { key: 'trace_id', name: 'trace_id', propertyFilterType: 'log' },
    { key: 'span_id', name: 'span_id', propertyFilterType: 'log' },
    { key: 'service_name', name: 'service_name', propertyFilterType: 'log' },
]

/**
 * Value suggestions for the log columns that have any. The `service_name` column is populated at
 * ingest from the resource `service.name` attribute, so that lookup is the only one whose values
 * the column can equal. The other keys keep their existing inputs: `message` is free text,
 * `severity_level` has an enum select, and the ids are pasted by hand.
 */
export function logsColumnValuesEndpoint(
    projectId: number | null,
    endpointFilters: Record<string, any> | undefined
): (key: string) => string | undefined {
    return (key: string) =>
        key === 'service_name'
            ? combineUrl(`api/projects/${projectId}/logs/values`, {
                  attribute_type: 'resource',
                  key: 'service.name',
                  ...endpointFilters,
              }).url
            : undefined
}
