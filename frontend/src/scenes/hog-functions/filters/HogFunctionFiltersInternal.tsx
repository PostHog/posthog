import { useValues } from 'kea'
import { useMemo } from 'react'

import { LemonSelect } from '@posthog/lemon-ui'

import { PropertyFilters } from 'lib/components/PropertyFilters/PropertyFilters'
import { TaxonomicFilterGroupType } from 'lib/components/TaxonomicFilter/types'
import { LemonField } from 'lib/lemon-ui/LemonField'
import { Link } from 'lib/lemon-ui/Link'
import { urls } from 'scenes/urls'

import { PropValue } from '~/models/propertyDefinitionsModel'
import { AnyPropertyFilter, CyclotronJobFiltersType, HogFunctionConfigurationContextId } from '~/types'

import { hogFunctionConfigurationLogic } from '../configuration/hogFunctionConfigurationLogic'
import {
    type FilterOption,
    getProductEventFilterOptions,
    getProductEventPropertyValues,
} from './productEventFilterOptions'

const getSimpleFilterValue = (value?: CyclotronJobFiltersType): string | undefined => {
    return value?.events?.[0]?.id
}

const setSimpleFilterValue = (
    options: FilterOption[],
    value: string,
    previous: CyclotronJobFiltersType | undefined,
    contextId: HogFunctionConfigurationContextId
): CyclotronJobFiltersType => {
    const next: CyclotronJobFiltersType = {
        source: 'internal-events',
        events: [
            {
                name: options.find((option) => option.value === value)?.label,
                id: value,
                type: 'events',
            },
        ],
    }
    // Preserve properties bound by Logs alerting (alert_id) and batch export alerts
    // (batch_export_id) — the trigger event id changes between the context's events, but the
    // binding to the parent resource must survive.
    if (
        (contextId === 'logs-alerting' || contextId === 'batch-export-alerts') &&
        previous?.properties &&
        previous.properties.length > 0
    ) {
        next.properties = previous.properties
    }
    return next
}

export function HogFunctionFiltersInternal(): JSX.Element {
    const { contextId } = useValues(hogFunctionConfigurationLogic)

    const options = useMemo(() => getProductEventFilterOptions(contextId), [contextId])

    const staticValueOptions = useMemo(
        () =>
            (propertyKey: string): PropValue[] | null =>
                getProductEventPropertyValues(contextId, propertyKey),
        [contextId]
    )

    const taxonomicGroupTypes = useMemo(() => {
        if (contextId === 'error-tracking') {
            return [
                TaxonomicFilterGroupType.ErrorTrackingIssues,
                TaxonomicFilterGroupType.ErrorTrackingProperties,
                TaxonomicFilterGroupType.EventProperties,
            ]
        } else if (contextId === 'insight-alerts') {
            return [TaxonomicFilterGroupType.Events]
        } else if (contextId === 'activity-log') {
            return [TaxonomicFilterGroupType.ActivityLogProperties]
        } else if (contextId === 'logs-alerting') {
            return [TaxonomicFilterGroupType.EventProperties]
        } else if (contextId === 'health-alerts') {
            return [TaxonomicFilterGroupType.EventProperties]
        } else if (contextId === 'batch-export-alerts') {
            return [TaxonomicFilterGroupType.EventProperties]
        }
        return []
    }, [contextId])

    return (
        <div className="p-3 rounded border deprecated-space-y-2 bg-surface-primary">
            <LemonField name="filters" label="Trigger">
                {({ value, onChange }) => (
                    <>
                        <div className="text-xs text-secondary">Choose what event should trigger this destination</div>
                        <LemonSelect
                            options={options}
                            value={getSimpleFilterValue(value)}
                            onChange={(next) => onChange(setSimpleFilterValue(options, next, value, contextId))}
                            placeholder="Select a filter"
                        />
                        {contextId === 'logs-alerting' ? <LogsAlertBindingHint filters={value} /> : null}
                        {taxonomicGroupTypes.length > 0 ? (
                            <PropertyFilters
                                key={contextId}
                                propertyFilters={value?.properties ?? []}
                                taxonomicGroupTypes={taxonomicGroupTypes}
                                onChange={(properties: AnyPropertyFilter[]) => {
                                    onChange({
                                        ...value,
                                        properties,
                                    })
                                }}
                                pageKey={`hog-function-internal-property-filters-${contextId}`}
                                buttonSize="small"
                                disablePopover
                                staticValueOptions={staticValueOptions}
                            />
                        ) : null}
                    </>
                )}
            </LemonField>
        </div>
    )
}

function LogsAlertBindingHint({ filters }: { filters: CyclotronJobFiltersType | undefined }): JSX.Element | null {
    const alertIdProp = filters?.properties?.find((p) => 'key' in p && p.key === 'alert_id')
    const rawValue = alertIdProp && 'value' in alertIdProp ? alertIdProp.value : undefined
    const alertId =
        typeof rawValue === 'string'
            ? rawValue
            : Array.isArray(rawValue) && typeof rawValue[0] === 'string'
              ? rawValue[0]
              : null

    if (!alertId) {
        return null
    }

    return (
        <div className="text-xs text-secondary flex items-center gap-1 flex-wrap">
            <span>Bound to alert</span>
            <Link to={urls.logsAlertDetail(alertId)}>
                <code className="text-xs">{alertId}</code>
            </Link>
        </div>
    )
}
