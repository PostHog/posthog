import { useActions, useValues } from 'kea'
import { PropertyMatchType } from 'posthog-js'
import { useMemo, useState } from 'react'

import { IconPlus, IconX } from '@posthog/icons'
import { LemonButton, LemonCard, LemonCheckbox, LemonCollapse } from '@posthog/lemon-ui'

import { PropertyFilters } from 'lib/components/PropertyFilters/PropertyFilters'
import { TaxonomicFilter } from 'lib/components/TaxonomicFilter/TaxonomicFilter'
import { TaxonomicFilterGroupType } from 'lib/components/TaxonomicFilter/types'
import { LemonField } from 'lib/lemon-ui/LemonField'
import { Popover } from 'lib/lemon-ui/Popover/Popover'

import { propertyDefinitionsModel } from '~/models/propertyDefinitionsModel'
import {
    AnyPropertyFilter,
    EventPropertyFilter,
    PropertyFilterType,
    PropertyOperator,
    PropertyType,
    SurveyEventsWithProperties,
} from '~/types'

import { surveyLogic } from './surveyLogic'

export function SurveyEventTrigger(): JSX.Element {
    const { survey, surveyRepeatedActivationAvailable } = useValues(surveyLogic)
    const { setSurveyValue } = useActions(surveyLogic)
    const { propertyDefinitionsByType } = useValues(propertyDefinitionsModel)
    const [addEventPopoverOpen, setAddEventPopoverOpen] = useState(false)

    // Only include operators supported by the SDK's property matching system
    // Exclude is_set and is_not_set as they're not supported
    const supportedOperators: PropertyOperator[] = [
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

    const events: SurveyEventsWithProperties[] = survey.conditions?.events?.values || []

    const updateEventAtIndex = (index: number, updatedEvent: SurveyEventsWithProperties): void => {
        const newEvents = [...events]
        newEvents[index] = updatedEvent
        setSurveyValue('conditions', {
            ...survey.conditions,
            events: {
                ...survey.conditions?.events,
                values: newEvents,
            },
        })
    }

    const removeEventAtIndex = (index: number): void => {
        const newEvents = events.filter((_, i) => i !== index)
        setSurveyValue('conditions', {
            ...survey.conditions,
            events: {
                ...survey.conditions?.events,
                values: newEvents,
            },
        })
    }

    const addEvent = (eventName: string): void => {
        setSurveyValue('conditions', {
            ...survey.conditions,
            events: {
                ...survey.conditions?.events,
                values: [...events, { name: eventName }],
            },
        })
    }

    const convertPropertyFiltersToArray = (
        propertyFilters?: SurveyEventsWithProperties['propertyFilters']
    ): EventPropertyFilter[] => {
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

    const convertArrayToPropertyFilters = (
        filters: AnyPropertyFilter[]
    ): SurveyEventsWithProperties['propertyFilters'] => {
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

    return (
        <LemonField.Pure
            label="User sends events"
            info="It only triggers when the event is captured in the current user session and using the PostHog SDK. Filtering by event properties requires posthog-js SDK at least v1.268.0, and it's supported only for web surveys."
        >
            <>
                {events.length === 0 ? (
                    <LemonCard className="border-dashed" hoverEffect={false}>
                        <div className="text-muted-alt text-sm mb-1">No events selected</div>
                        <div className="text-xs text-muted">
                            Add events to trigger this survey when those events are captured in the current user session
                        </div>
                    </LemonCard>
                ) : (
                    <div className="space-y-2">
                        {events.map((event, index) => {
                            const hasPropertyFilters =
                                event.propertyFilters && Object.keys(event.propertyFilters).length > 0

                            return (
                                <LemonCollapse
                                    key={`${event.name}-${index}`}
                                    panels={[
                                        {
                                            key: `event-${index}`,
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
                                                        pageKey={`survey-event-${event.name}-${index}`}
                                                        taxonomicGroupTypes={[TaxonomicFilterGroupType.EventProperties]}
                                                        excludedProperties={excludedObjectProperties}
                                                        eventNames={[event.name]}
                                                        buttonText="Add property filter"
                                                        buttonSize="small"
                                                        operatorAllowlist={supportedOperators}
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

                {surveyRepeatedActivationAvailable && (
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

                <Popover
                    className="mt-2"
                    overlay={
                        <TaxonomicFilter
                            groupType={TaxonomicFilterGroupType.Events}
                            value=""
                            onChange={(_, value) => {
                                if (typeof value === 'string') {
                                    const eventName = value
                                    const currentEventNames = events.map((e) => e.name)

                                    // Only add if not already selected
                                    if (!currentEventNames.includes(eventName)) {
                                        addEvent(eventName)
                                    }
                                    setAddEventPopoverOpen(false)
                                }
                            }}
                            allowNonCapturedEvents
                            taxonomicGroupTypes={[
                                TaxonomicFilterGroupType.CustomEvents,
                                TaxonomicFilterGroupType.Events,
                            ]}
                        />
                    }
                    visible={addEventPopoverOpen}
                    onClickOutside={() => setAddEventPopoverOpen(false)}
                    placement="bottom-start"
                >
                    <LemonButton
                        type="secondary"
                        icon={<IconPlus />}
                        onClick={() => setAddEventPopoverOpen(!addEventPopoverOpen)}
                        size="small"
                        className="w-fit"
                    >
                        Add event
                    </LemonButton>
                </Popover>
            </>
        </LemonField.Pure>
    )
}
