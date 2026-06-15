import { useValues } from 'kea'
import { useMemo } from 'react'

import { LemonSelect } from '@posthog/lemon-ui'

import { PropertyFilters } from 'lib/components/PropertyFilters/PropertyFilters'
import { TaxonomicFilterGroupType } from 'lib/components/TaxonomicFilter/types'
import { LemonField } from 'lib/lemon-ui/LemonField'
import { Link } from 'lib/lemon-ui/Link'
import { urls } from 'scenes/urls'

import { AnyPropertyFilter, CyclotronJobFiltersType, HogFunctionConfigurationContextId } from '~/types'

import { hogFunctionConfigurationLogic } from '../configuration/hogFunctionConfigurationLogic'

type FilterOption = { value: string; label: string }

// NOTE: This is all a bit WIP and will be improved upon over time
// TODO: Make this more advanced with sub type filtering etc.
// TODO: Make it possible for the renderer to limit the options based on the type
/**
 * Options for the 'Trigger' field on the new destination page
 */
export const getProductEventFilterOptions = (contextId: HogFunctionConfigurationContextId): FilterOption[] => {
    switch (contextId) {
        case 'error-tracking':
            return [
                {
                    label: 'Error tracking issue created',
                    value: '$error_tracking_issue_created',
                },
                {
                    label: 'Error tracking issue reopened',
                    value: '$error_tracking_issue_reopened',
                },
            ]
        case 'insight-alerts':
            return [
                {
                    label: 'Insight alert firing',
                    value: '$insight_alert_firing',
                },
            ]
        case 'logs-alerting':
            return [
                {
                    label: 'Log alert firing',
                    value: '$logs_alert_firing',
                },
                {
                    label: 'Log alert resolved',
                    value: '$logs_alert_resolved',
                },
                {
                    label: 'Log alert auto-disabled',
                    value: '$logs_alert_auto_disabled',
                },
                {
                    label: 'Log alert errored',
                    value: '$logs_alert_errored',
                },
            ]
        case 'discussion-mention':
            return [
                {
                    label: 'Discussion mention',
                    value: '$discussion_mention_created',
                },
            ]
        case 'health-alerts':
            return [
                {
                    label: 'Health check fired',
                    value: '$health_check_issue_firing',
                },
                {
                    label: 'Health check resolved',
                    value: '$health_check_issue_resolved',
                },
            ]
        default:
            return [
                {
                    label: 'Team activity',
                    value: '$activity_log_entry_created',
                },
                {
                    label: 'Early access feature updated',
                    value: '$early_access_feature_updated',
                },
            ]
    }
}

export const getProductEventPropertyFilterOptions = (contextId: HogFunctionConfigurationContextId): string[] => {
    switch (contextId) {
        case 'activity-log':
            return [
                'id',
                'unread',
                'organization_id',
                'was_impersonated',
                'is_system',
                'activity',
                'item_id',
                'scope',
                'detail',
                'detail.name',
                'detail.changes',
                'created_at',
            ]
        case 'error-tracking':
            return [
                '$exception_types',
                '$exception_values',
                '$exception_sources',
                '$exception_functions',
                '$exception_handled',
            ]
    }

    return []
}

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
        events: [
            {
                name: options.find((option) => option.value === value)?.label,
                id: value,
                type: 'events',
            },
        ],
    }
    // Preserve properties bound by Logs alerting (alert_id) — the trigger event id changes between
    // firing/resolved/auto-disabled/errored, but the binding to the parent alert must survive.
    if (contextId === 'logs-alerting' && previous?.properties && previous.properties.length > 0) {
        next.properties = previous.properties
    }
    return next
}

export function HogFunctionFiltersInternal(): JSX.Element {
    const { contextId } = useValues(hogFunctionConfigurationLogic)

    const options = useMemo(() => getProductEventFilterOptions(contextId), [contextId])

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
