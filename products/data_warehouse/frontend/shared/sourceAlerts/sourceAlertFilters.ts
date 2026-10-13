import { getFiltersFromSubTemplateId } from 'scenes/hog-functions/list/LinkedHogFunctions'

import {
    CyclotronJobFilterPropertyFilter,
    CyclotronJobFiltersType,
    PropertyFilterType,
    PropertyOperator,
} from '~/types'

import { SOURCE_ALERT_SUB_TEMPLATE_IDS } from './sourceAlertWizardConfig'

export function buildSourceAlertPropertyFilters(sourceId?: string): CyclotronJobFilterPropertyFilter[] {
    if (!sourceId) {
        return []
    }
    return [
        {
            key: 'source_id',
            type: PropertyFilterType.Event,
            value: sourceId,
            operator: PropertyOperator.Exact,
        },
    ]
}

export function buildSourceAlertFilterGroups(sourceId?: string): CyclotronJobFiltersType[] {
    const properties = buildSourceAlertPropertyFilters(sourceId)
    return SOURCE_ALERT_SUB_TEMPLATE_IDS.flatMap((id) => {
        const filters = getFiltersFromSubTemplateId(id)
        if (!filters) {
            return []
        }
        return [properties.length > 0 ? { ...filters, properties } : filters]
    })
}

export function buildSourceAlertNameSuffix(sourceId?: string, sourceName?: string): string | undefined {
    return sourceId && sourceName ? `for ${sourceName}` : undefined
}
