import { useActions, useValues } from 'kea'
import { PropertyMatchType } from 'posthog-js'
import { useMemo } from 'react'

import { IconX } from '@posthog/icons'
import { LemonCard, LemonCheckbox, LemonCollapse } from '@posthog/lemon-ui'

import { PropertyFilters } from 'lib/components/PropertyFilters/PropertyFilters'
import { TaxonomicFilterGroupType } from 'lib/components/TaxonomicFilter/types'
import { LemonField } from 'lib/lemon-ui/LemonField'

import { propertyDefinitionsModel } from '~/models/propertyDefinitionsModel'
import {
    AnyPropertyFilter,
    EventPropertyFilter,
    PropertyFilterType,
    PropertyOperator,
    PropertyType,
    SurveyEventsWithProperties,
} from '~/types'

import { AddEventButton } from './AddEventButton'
import { surveyLogic } from './surveyLogic'

// Only include operators supported by the SDK's property matching system
// Exclude is_set and is_not_set as they're not supported
export const SUPPORTED_OPERATORS: PropertyOperator[] = [
    'exact',
    'is_not',
    'icontains',
    'not_icontains',
    'regex',
    'not_regex',
    'gt',
    'gte',
    'lt',
    'lte',
] as PropertyOperator[]

export function convertPropertyFiltersToArray(
    propertyFilters?: SurveyEventsWithProperties['propertyFilters']
): EventPropertyFilter[] {
    if (!propertyFilters) {
        return []
    }

    return Object.entries(propertyFilters).map(([key, filter]) => ({
        key,
        value: filter.values,
        operator: filter.operator as PropertyOperator,
        type: PropertyFilterType.Event,
    }))
}

export function convertArrayToPropertyFilters(
    filters: AnyPropertyFilter[]
): SurveyEventsWithProperties['propertyFilters'] {
    if (filters.length === 0) {
        return undefined
    }

    const propertyFilters: SurveyEventsWithProperties['propertyFilters'] = {}
    filters.forEach((filter) => {
        if (filter.key && 'operator' in filter) {
            propertyFilters[filter.key] = {
                values: Array.isArray(filter.value) ? filter.value.map(String) : [String(filter.value)],
                operator: filter.operator as PropertyMatchType,
            }
        }
    })
    return propertyFilters
}

export function getEventPropertyFilterCount(propertyFilters?: SurveyEventsWithProperties['propertyFilters']): number {
    return propertyFilters ? Object.keys(propertyFilters).length : 0
}

export function useExcludedObjectProperties(): Record<TaxonomicFilterGroupType.EventProperties, string[]> {
    const { propertyDefinitionsByType } = useValues(propertyDefinitionsModel)

    return useMemo(() => {
        const eventProperties = propertyDefinitionsByType('event')
        const objectProperties = eventProperties.filter((prop) => {
            // Exclude StringArray (arrays/objects) and undefined property types. Only primitive types are supported for
            // comparison purposes in the JS SDK.
            return !prop.property_type || prop.property_type === PropertyType.StringArray
        })
        return {
            [TaxonomicFilterGroupType.EventProperties]: objectProperties.map((prop) => prop.name),
        }
    }, [propertyDefinitionsByType])
}

interface SurveyEventSelectorProps {
    conditionField: 'events' | 'cancelEvents'
    label: string
    info: string
    emptyTitle: string
    emptyDescription: string
    addButtonText?: string
    showRepeatedActivation?: boolean
}

function SurveyEventSelector({
    conditionField,
    label,
    info,
    emptyTitle,
    emptyDescription,
    addButtonText,
    showRepeatedActivation = false,
}: SurveyEventSelectorProps): JSX.Element {
    const { survey, surveyRepeatedActivationAvailable } = useValues(surveyLogic)
    const { setSurveyValue } = useActions(surveyLogic)
    const excludedObjectProperties = useExcludedObjectProperties()

    // Defend against surveys persisted with a non-array `values` shape - a truthy non-array would
    // slip past `|| []` and blow up the later `events.map(...)` calls with "v.map is not a function".
    const rawValues = survey.conditions?.[conditionField]?.values
    const events: SurveyEventsWithProperties[] = Array.isArray(rawValues) ? rawValues : []

    const updateEventAtIndex = (index: number, updatedEvent: SurveyEventsWithProperties): void => {
        const newEvents = [...events]
        newEvents[index] = updatedEvent
        setSurveyValue('conditions', {
            ...survey.conditions,
            [conditionField]: {
                ...survey.conditions?.[conditionField],
                values: newEvents,
            },
        })
    }

    const removeEventAtIndex = (index: number): void => {
        const newEvents = events.filter((_, i) => i !== index)
        setSurveyValue('conditions', {
            ...survey.conditions,
            [conditionField]: {
                ...survey.conditions?.[conditionField],
                values: newEvents,
            },
        })
    }

    const addEvent = (eventName: string): void => {
        setSurveyValue('conditions', {
            ...survey.conditions,
            [conditionField]: {
                ...survey.conditions?.[conditionField],
                values: [...events, { name: eventName }],
            },
        })
    }

    return (
        <LemonField.Pure label={label} info={info}>
            <>
                {events.length === 0 ? (
                    <LemonCard className="border-dashed" hoverEffect={false}>
                        <div className="text-muted-alt text-sm mb-1">{emptyTitle}</div>
                        <div className="text-xs text-muted">{emptyDescription}</div>
                    </LemonCard>
                ) : (
                    <div className="space-y-2">
                        {events.map((event, index) => {
                            const propertyFilterCount = getEventPropertyFilterCount(event.propertyFilters)
                            const hasPropertyFilters = propertyFilterCount > 0
                            const panelKey = `${conditionField}-event-${index}`

                            return (
                                <LemonCollapse
                                    key={`${conditionField}-${event.name}-${index}`}
                                    defaultActiveKey={panelKey}
                                    panels={[
                                        {
                                            key: panelKey,
                                            // sideAction keeps the remove button a sibling of the header <button> - a
                                            // button can't nest inside a button
                                            header: {
                                                children: (
                                                    <div className="flex items-center gap-2 min-w-0">
                                                        <span className="font-semibold text-sm truncate">
                                                            {event.name}
                                                        </span>
                                                        <span className="text-xs text-muted bg-border px-1.5 py-0.5 rounded shrink-0">
                                                            {hasPropertyFilters
                                                                ? `${propertyFilterCount} filter${propertyFilterCount !== 1 ? 's' : ''}`
                                                                : 'No filters'}
                                                        </span>
                                                    </div>
                                                ),
                                                sideAction: {
                                                    icon: <IconX />,
                                                    onClick: () => removeEventAtIndex(index),
                                                    tooltip: 'Remove event',
                                                },
                                            },
                                            content: (
                                                <div className="space-y-2">
                                                    <PropertyFilters
                                                        propertyFilters={convertPropertyFiltersToArray(
                                                            event.propertyFilters
                                                        )}
                                                        onChange={(filters: AnyPropertyFilter[]) => {
                                                            const updatedEvent: SurveyEventsWithProperties = {
                                                                ...event,
                                                                propertyFilters: convertArrayToPropertyFilters(filters),
                                                            }
                                                            updateEventAtIndex(index, updatedEvent)
                                                        }}
                                                        pageKey={`survey-${conditionField}-${event.name}-${index}`}
                                                        taxonomicGroupTypes={[TaxonomicFilterGroupType.EventProperties]}
                                                        excludedProperties={excludedObjectProperties}
                                                        eventNames={[event.name]}
                                                        buttonText="Add property filter"
                                                        buttonSize="small"
                                                        operatorAllowlist={SUPPORTED_OPERATORS}
                                                    />
                                                    <p className="text-xs text-muted m-0">
                                                        Array and object properties aren't supported here.
                                                    </p>
                                                </div>
                                            ),
                                        },
                                    ]}
                                />
                            )
                        })}
                    </div>
                )}

                {showRepeatedActivation && surveyRepeatedActivationAvailable && (
                    <LemonCheckbox
                        label="Show every time these events fire (otherwise: once per user)"
                        checked={survey.conditions?.events?.repeatedActivation || false}
                        onChange={(checked) => {
                            setSurveyValue('conditions', {
                                ...survey.conditions,
                                events: {
                                    ...survey.conditions?.events,
                                    repeatedActivation: checked,
                                },
                            })
                        }}
                    />
                )}

                <AddEventButton
                    onEventSelect={(eventName) => addEvent(eventName)}
                    excludedEvents={events.map((e) => e.name)}
                    addButtonText={addButtonText}
                />
            </>
        </LemonField.Pure>
    )
}

export function SurveyEventTrigger(): JSX.Element {
    return (
        <SurveyEventSelector
            conditionField="events"
            label="User sends events"
            info="Triggers fire when the event is captured in the current user session via a PostHog SDK. Property filtering requires posthog-js 1.268+ or posthog-react-native 4.15+."
            emptyTitle="No events selected"
            emptyDescription="Pick events that should trigger this survey."
            showRepeatedActivation
        />
    )
}

export function SurveyCancelEventTrigger(): JSX.Element {
    const { survey } = useValues(surveyLogic)
    const delaySeconds = survey.appearance?.surveyPopupDelaySeconds

    return (
        <SurveyEventSelector
            conditionField="cancelEvents"
            label="Cancel survey on events"
            info="Triggers fire when the event is captured in the current user session via a PostHog SDK. Requires posthog-js 1.299+. Web surveys only."
            emptyTitle={`During your ${delaySeconds} second delay...`}
            emptyDescription="If any of these events fire, the survey is cancelled — useful when the user has already completed the action."
            addButtonText="Add cancel event"
        />
    )
}
