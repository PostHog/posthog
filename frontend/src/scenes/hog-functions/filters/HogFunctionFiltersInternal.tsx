import { LemonSelect } from '@posthog/lemon-ui'
import { useValues } from 'kea'
import { PropertyFilters } from 'lib/components/PropertyFilters/PropertyFilters'
import { TaxonomicFilterGroupType } from 'lib/components/TaxonomicFilter/types'
import { useFeatureFlag } from 'lib/hooks/useFeatureFlag'
import { LemonField } from 'lib/lemon-ui/LemonField'
import { useMemo } from 'react'

import { AnyPropertyFilter, HogFunctionConfigurationContextId, HogFunctionFiltersType } from '~/types'

import { hogFunctionConfigurationLogic } from '../configuration/hogFunctionConfigurationLogic'

type FilterOption = { value: string; label: string }

// NOTE: This is all a bit WIP and will be improved upon over time
// TODO: Make this more advanced with sub type filtering etc.
// TODO: Make it possible for the renderer to limit the options based on the type
/**
 * Options for the 'Trigger' field on the new destination page
 */
const getFilterOptions = (contextId: HogFunctionConfigurationContextId): FilterOption[] => {
    if (contextId === 'error-tracking') {
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
    }
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

const getSimpleFilterValue = (value?: HogFunctionFiltersType): string | undefined => {
    return value?.events?.[0]?.id
}

const setSimpleFilterValue = (options: FilterOption[], value: string): HogFunctionFiltersType => {
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

export function HogFunctionFiltersInternal(): JSX.Element {
    const {
        logicProps: { id },
        contextId,
    } = useValues(hogFunctionConfigurationLogic)

    const options = useMemo(() => getFilterOptions(contextId), [contextId])
    const hasAlertRouting = useFeatureFlag('ERROR_TRACKING_ALERT_ROUTING')
    const showPropertyFilters = (hasAlertRouting && contextId === 'error-tracking') || contextId === 'insight-alerts'

    const taxonomicGroupTypes = useMemo(() => {
        if (contextId === 'error-tracking') {
            return [TaxonomicFilterGroupType.ErrorTrackingIssues]
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
                            onChange={(value) => onChange(setSimpleFilterValue(options, value))}
                            placeholder="Select a filter"
                        />
                        {showPropertyFilters ? (
                            <PropertyFilters
                                propertyFilters={value?.properties ?? []}
                                taxonomicGroupTypes={taxonomicGroupTypes}
                                onChange={(properties: AnyPropertyFilter[]) => {
                                    onChange({
                                        ...value,
                                        properties,
                                    })
                                }}
                                pageKey="hog-function-internal-property-filters"
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
