import { useActions, useValues } from 'kea'
import { PropertyMatchType } from 'posthog-js'
import { useMemo } from 'react'

import { IconX } from '@posthog/icons'
import { LemonButton, LemonCard, LemonCheckbox, LemonCollapse } from '@posthog/lemon-ui'

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
    const { propertyDefinitionsByType } = useValues(propertyDefinitionsModel)

    const excludedObjectProperties = useMemo(() => {
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

    const events: SurveyEventsWithProperties[] = survey.conditions?.[conditionField]?.values || []

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
                            const hasPropertyFilters =
                                event.propertyFilters && Object.keys(event.propertyFilters).length > 0

                            return (
                                <LemonCollapse
                                    key={`${conditionField}-${event.name}-${index}`}
                                    panels={[
                                        {
                                            key: `${conditionField}-event-${index}`,
                                            header: {
                                                children: (
                                                    <div className="flex items-center justify-between flex-1">
                                                        <div className="flex items-center gap-2">
                                                            <span className="font-semibold text-sm">{event.name}</span>
                                                            {hasPropertyFilters && (
                                                                <span className="text-xs text-muted bg-border px-1.5 py-0.5 rounded">
                                                                    {Object.keys(event.propertyFilters!).length} filter
                                                                    {Object.keys(event.propertyFilters!).length !== 1
                                                                        ? 's'
                                                                        : ''}
                                                                </span>
                                                            )}
                                                        </div>
                                                        <LemonButton
                                                            size="xsmall"
                                                            icon={<IconX />}
                                                            onClick={(e) => {
                                                                e.stopPropagation()
                                                                removeEventAtIndex(index)
                                                            }}
                                                            type="tertiary"
                                                            status="alt"
                                                        />
                                                    </div>
                                                ),
                                            },
                                            content: (
                                                <div>
                                                    <div className="text-xs font-medium text-muted-alt mb-2 uppercase tracking-wide">
                                                        Property Filters
                                                    </div>
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
                                                    <span className="text-xs text-muted">
                                                        Only primitive types (strings, numbers, booleans) are supported
                                                        for property filters. Array and object properties are not
                                                        supported and will not be shown.
                                                    </span>
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
                        label="Display the survey every time events occur, instead of only once per user"
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
            info="It only triggers when the event is captured in the current user session and using the PostHog SDK. Filtering by event properties requires posthog-js >= v1.268.0 or posthog-react-native >= v4.15.0. Not supported for other SDKs."
            emptyTitle="No events selected"
            emptyDescription="Add events to trigger this survey when those events are captured in the current user session"
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
            info="It only triggers when the event is captured in the current user session and using the PostHog SDK. Requires posthog-js SDK at least v1.299.0, and it's supported only for web surveys."
            emptyTitle={`During your ${delaySeconds} second delay...`}
            emptyDescription="If any of these events fire, the survey will be cancelled. Useful for not interrupting users who complete an action successfully."
            addButtonText="Add cancel event"
        />
    )
}
