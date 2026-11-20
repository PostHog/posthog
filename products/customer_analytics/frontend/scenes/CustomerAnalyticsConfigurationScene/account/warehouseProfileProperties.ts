import { combineUrl } from 'kea-router'

import { humanFriendlyNumber } from 'lib/utils/numbers'
import { urls } from 'scenes/urls'

import type {
    CustomPropertyDefinitionApi,
    CustomPropertySourceApi,
} from 'products/customer_analytics/frontend/generated/api.schemas'

import { type SourceSyncStatus, sourceSyncStatus } from './customPropertyTypes'

// Labels that differ between the person- and group-target views of the same warehouse-sync machinery.
export type ProfileLabels = { entity: string; entityPlural: string; keyColumn: string }
export const LABELS_BY_TARGET: Record<'person' | 'group', ProfileLabels> = {
    person: { entity: 'person', entityPlural: 'people', keyColumn: 'Distinct ID column' },
    group: { entity: 'group', entityPlural: 'groups', keyColumn: 'Group key column' },
}

// Whether the source reads a materialized view rather than a synced table.
export function bindsAView(source: CustomPropertySourceApi): boolean {
    return !!source.saved_query && !source.external_data_schema
}

// Where the bound table or view's own run history lives. Null when the source has no warehouse
// binding, or when the caller can't view what it reads.
export function sourceRunsUrl(source: CustomPropertySourceApi): string | null {
    if (bindsAView(source)) {
        // The view's page is keyed by its data modeling node; `lookup` lets it resolve from the saved query id.
        return source.saved_query
            ? combineUrl(urls.nodeDetail(source.saved_query, 'materialization'), { lookup: 'saved_query' }).url
            : null
    }
    if (!source.external_data_source || !source.external_data_schema) {
        return null
    }
    return urls.dataWarehouseSourceSchema(source.external_data_source, source.external_data_schema, 'syncs')
}

export function syncStatusSummary(
    source: CustomPropertySourceApi,
    labels: ProfileLabels
): { status: SourceSyncStatus; tooltipTitle: string | undefined } {
    const latestRun = source.latest_run
    const status = sourceSyncStatus(source)
    // Only report an affected count for a finished run — an in-progress/failed run's count
    // isn't "the last run". status.tooltip is undefined for the synced/pending states, so
    // build the title from the present parts rather than interpolating undefined into it.
    const affected = latestRun?.status === 'completed' ? latestRun.existing : undefined
    const tooltipTitle =
        [
            status.tooltip,
            affected != null
                ? `${humanFriendlyNumber(affected)} ${labels.entityPlural} affected on the last run`
                : null,
        ]
            .filter(Boolean)
            .join(' — ') || undefined
    return { status, tooltipTitle }
}

export function rowActionState(
    definition: CustomPropertyDefinitionApi,
    triggeringSourceIds: string[],
    restrictionReason: string | null
): {
    source: CustomPropertySourceApi | null | undefined
    triggering: boolean
    running: boolean
    disabledReason: string | null | undefined
} {
    const source = definition.source
    const triggering = !!source && triggeringSourceIds.includes(source.id)
    const running = source?.latest_run?.status === 'running'
    // A run is in flight for this table; block a second trigger and show it as busy.
    const busyReason = running ? 'A sync or backfill is already running for this table' : undefined
    const disabledReason = restrictionReason ?? (!source ? 'No source configured' : undefined) ?? busyReason
    return { source, triggering, running, disabledReason }
}
