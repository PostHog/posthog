import { FacetOption } from 'lib/components/FacetRail/Facet'
import { FacetGroupItem } from 'lib/components/FacetRail/facetGroups'

import { PlatformAlertFacetsApi, PlatformAlertsListParams } from './generated/api.schemas'
import { SOURCE_KINDS, STATUS_LABELS } from './platformAlertFormat'

export type PlatformAlertFilterParam = 'state' | 'muted' | 'source_kind' | 'label'

/** The values chosen in each facet, keyed by the list parameter that takes them. A label value is `key:value`. */
export type PlatformAlertFilters = Record<PlatformAlertFilterParam, string[]>

export const NO_PLATFORM_ALERT_FILTERS: PlatformAlertFilters = { state: [], muted: [], source_kind: [], label: [] }

export interface PlatformAlertFacet extends FacetGroupItem {
    param: PlatformAlertFilterParam
    options: FacetOption[]
}

const MUTE_LABELS: Record<string, string> = { snoozed: 'Snoozed', quiet_hours: 'Quiet hours' }

/** The rail's facets in the order the list reads them: state, mute, type, then one facet for each label key. */
export function platformAlertFacets(facets: PlatformAlertFacetsApi | null): PlatformAlertFacet[] {
    if (!facets) {
        return []
    }
    return [
        {
            key: 'state',
            title: 'State',
            group: 'Alerts',
            param: 'state',
            options: facets.states.map(({ value, count }) => ({ value, count, label: STATUS_LABELS[value] ?? value })),
        },
        {
            key: 'muted',
            title: 'Muted',
            group: 'Alerts',
            param: 'muted',
            options: facets.mutes.map(({ value, count }) => ({ value, count, label: MUTE_LABELS[value] ?? value })),
        },
        {
            key: 'source_kind',
            title: 'Type',
            group: 'Alerts',
            param: 'source_kind',
            options: facets.source_kinds.map(({ value, count }) => ({
                value,
                count,
                label: SOURCE_KINDS[value]?.label ?? value,
            })),
        },
        ...facets.labels.map(({ key, values }) => ({
            key: `label:${key}`,
            title: key,
            group: 'Labels',
            param: 'label' as const,
            options: values.map(({ value, count }) => ({ value: `${key}:${value}`, count, label: value })),
        })),
    ]
}

/** The list request's filter parameters, leaving out each facet with nothing chosen. */
export function platformAlertsListFilterParams(filters: PlatformAlertFilters): Partial<PlatformAlertsListParams> {
    // The chosen values come from the facets response, which uses the list's own vocabularies.
    return Object.fromEntries(
        Object.entries(filters).filter(([, values]) => values.length > 0)
    ) as Partial<PlatformAlertsListParams>
}
