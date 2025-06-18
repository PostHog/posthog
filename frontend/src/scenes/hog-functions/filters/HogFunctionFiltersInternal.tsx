import { LemonSelect } from '@posthog/lemon-ui'
import { useValues } from 'kea'
import { PropertyFilters } from 'lib/components/PropertyFilters/PropertyFilters'
import { TaxonomicFilterGroupType } from 'lib/components/TaxonomicFilter/types'
import { useFeatureFlag } from 'lib/hooks/useFeatureFlag'
import { LemonField } from 'lib/lemon-ui/LemonField'
import { useMemo } from 'react'

import { ErrorTrackingIssueAssignee } from '~/queries/schema/schema-general'
import {
    AnyPropertyFilter,
    CyclotronJobFiltersType,
    ErrorTrackingIssueFilter,
    HogFunctionConfigurationContextId,
} from '~/types'

import { hogFunctionConfigurationLogic } from '../configuration/hogFunctionConfigurationLogic'

type FilterOption = { value: string; label: string }

// NOTE: This is all a bit WIP and will be improved upon over time
// TODO: Make this more advanced with sub type filtering etc.
// TODO: Make it possible for the renderer to limit the options based on the type
/**
 * Options for the 'Trigger' field on the new destination page
 */
const getFilterOptions = (contextId: HogFunctionConfigurationContextId): FilterOption[] => {
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

const getSimpleFilterValue = (value?: CyclotronJobFiltersType): string | undefined => {
    return value?.events?.[0]?.id
}

const setSimpleFilterValue = (options: FilterOption[], value: string): CyclotronJobFiltersType => {
    return {
        events: [
            {
                name: options.find((option) => option.value === value)?.label,
                id: value,
                type: 'events',
            },
        ],
    }
}

const serializePropertyFilters = (
    contextId: HogFunctionConfigurationContextId,
    properties?: AnyPropertyFilter[]
): AnyPropertyFilter[] => {
    const newProperties = properties ?? []
    switch (contextId) {
        case 'error-tracking':
            return newProperties.map((p) => {
                if (p.key && ['assigned_user_group_id', 'assigned_user_id', 'assigned_role_id'].includes(p.key)) {
                    const type = p.key.match(/^assigned_(.*)_id$/)?.[1] ?? 'user'
                    const value = { type, id: Number(p.value) } as ErrorTrackingIssueAssignee
                    return { ...p, key: 'assignee', value } as ErrorTrackingIssueFilter
                }
                return p
            })
        default:
            return newProperties
    }
}

const deserializePropertyFilters = (
    contextId: HogFunctionConfigurationContextId,
    properties: AnyPropertyFilter[]
): AnyPropertyFilter[] => {
    switch (contextId) {
        case 'error-tracking':
            return properties.map((p) => {
                if (p.key === 'assignee') {
                    const { type, id } = p.value as ErrorTrackingIssueAssignee
                    return { ...p, key: `assigned_${type}_id`, value: id }
                }
                return p
            })
        default:
            return properties
    }
}

export function HogFunctionFiltersInternal(): JSX.Element {
    const { contextId } = useValues(hogFunctionConfigurationLogic)

    const options = useMemo(() => getFilterOptions(contextId), [contextId])
    const hasAlertRouting = useFeatureFlag('ERROR_TRACKING_ALERT_ROUTING')

    const taxonomicGroupTypes = useMemo(() => {
        if (hasAlertRouting && contextId === 'error-tracking') {
            return [TaxonomicFilterGroupType.ErrorTrackingIssues]
        } else if (contextId === 'insight-alerts') {
            return [TaxonomicFilterGroupType.Events]
        }
        return []
    }, [contextId, hasAlertRouting])

    return (
        <div className="p-3 rounded border deprecated-space-y-2 bg-surface-primary">
            <LemonField name="filters" label="Trigger">
                {({ value, onChange }) => (
                    <>
                        <div className="text-xs text-secondary">Choose what event should trigger this destination</div>
                        <LemonSelect
                            options={options}
                            value={getSimpleFilterValue(value)}
                            onChange={(value) => onChange(setSimpleFilterValue(options, value))}
                            placeholder="Select a filter"
                        />
                        {taxonomicGroupTypes.length > 0 ? (
                            <PropertyFilters
                                key={contextId}
                                propertyFilters={serializePropertyFilters(contextId, value?.properties)}
                                taxonomicGroupTypes={taxonomicGroupTypes}
                                onChange={(properties: AnyPropertyFilter[]) => {
                                    onChange({
                                        ...value,
                                        properties: deserializePropertyFilters(contextId, properties),
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
