import { useActions, useValues } from 'kea'

import { IconX } from '@posthog/icons'
import { LemonButton, LemonCheckbox, LemonInput } from '@posthog/lemon-ui'

import { PropertyFilters } from 'lib/components/PropertyFilters/PropertyFilters'
import { TaxonomicFilterGroupType } from 'lib/components/TaxonomicFilter/types'
import { LemonRadio } from 'lib/lemon-ui/LemonRadio'
import { AddEventButton } from 'scenes/surveys/AddEventButton'

import { AnyPropertyFilter, SurveyAppearance, SurveyDisplayConditions, SurveyEventsWithProperties } from '~/types'

import {
    SUPPORTED_OPERATORS,
    convertArrayToPropertyFilters,
    convertPropertyFiltersToArray,
    getEventPropertyFilterCount,
    useExcludedObjectProperties,
} from '../../SurveyEventTrigger'
import { surveyLogic } from '../../surveyLogic'

export function WhenStep(): JSX.Element {
    const { survey } = useValues(surveyLogic)
    const { setSurveyValue } = useActions(surveyLogic)

    const conditions: Partial<SurveyDisplayConditions> = survey.conditions || {}
    const appearance: Partial<SurveyAppearance> = survey.appearance || {}
    const triggerEvents = conditions.events?.values || []
    // Check if events object exists (even if empty) to determine mode
    const triggerMode = conditions.events !== null && conditions.events !== undefined ? 'event' : 'pageview'
    const repeatedActivation = conditions.events?.repeatedActivation ?? false
    const delaySeconds = appearance.surveyPopupDelaySeconds ?? 0
    const excludedObjectProperties = useExcludedObjectProperties()

    const setTriggerMode = (mode: 'pageview' | 'event'): void => {
        if (mode === 'pageview') {
            setSurveyValue('conditions', { ...conditions, events: null })
        } else {
            // Initialize empty events structure to switch to event mode
            setSurveyValue('conditions', { ...conditions, events: { values: [], repeatedActivation: false } })
        }
    }

    const setDelaySeconds = (seconds: number): void => {
        setSurveyValue('appearance', { ...appearance, surveyPopupDelaySeconds: seconds })
    }

    const setRepeatedActivation = (enabled: boolean): void => {
        setSurveyValue('conditions', {
            ...conditions,
            events: { ...conditions.events, values: conditions.events?.values || [], repeatedActivation: enabled },
        })
    }

    const addTriggerEvent = (eventName: string): void => {
        const currentEvents = conditions.events?.values || []
        if (!currentEvents.some((e) => e.name === eventName)) {
            setSurveyValue('conditions', {
                ...conditions,
                events: {
                    ...conditions.events,
                    values: [...currentEvents, { name: eventName }],
                },
            })
        }
    }

    const removeTriggerEvent = (eventName: string): void => {
        const currentEvents = conditions.events?.values || []
        const newEvents = currentEvents.filter((e) => e.name !== eventName)
        setSurveyValue('conditions', {
            ...conditions,
            events: newEvents.length > 0 ? { ...conditions.events, values: newEvents } : null,
        })
    }

    const updateTriggerEvent = (eventName: string, updatedEvent: SurveyEventsWithProperties): void => {
        const currentEvents = conditions.events?.values || []
        const newEvents = currentEvents.map((event) => (event.name === eventName ? updatedEvent : event))
        setSurveyValue('conditions', {
            ...conditions,
            events: {
                ...conditions.events,
                values: newEvents,
            },
        })
    }

    const updateTriggerEventFilters = (event: SurveyEventsWithProperties, filters: AnyPropertyFilter[]): void => {
        updateTriggerEvent(event.name, {
            ...event,
            propertyFilters: convertArrayToPropertyFilters(filters),
        })
    }

    return (
        <div className="space-y-6">
            <div className="space-y-1">
                <h2 className="text-xl font-semibold">When should this appear?</h2>
                <p className="text-secondary text-sm">Choose when to show this survey to your users</p>
            </div>

            <LemonRadio
                value={triggerMode}
                onChange={setTriggerMode}
                options={[
                    {
                        value: 'pageview',
                        label: 'On page load',
                        description: 'Shows when the user visits the page',
                    },
                    {
                        value: 'event',
                        label: 'When an event is captured',
                        description: 'Trigger the survey after specific events occur',
                    },
                ]}
            />

            {triggerMode === 'event' && (
                <div className="ml-6 space-y-3">
                    {triggerEvents.length > 0 && (
                        <div className="space-y-3">
                            <div className="text-xs text-muted">
                                Each event can be narrowed with optional property filters right below it.
                            </div>
                            {triggerEvents.map((event) => {
                                const propertyFilterCount = getEventPropertyFilterCount(event.propertyFilters)

                                return (
                                    <div key={event.name} className="border border-border rounded-lg bg-bg-light p-3">
                                        <div className="flex items-start justify-between gap-3 mb-3">
                                            <div className="space-y-1">
                                                <div className="flex flex-wrap items-center gap-2">
                                                    <code className="text-sm font-mono">{event.name}</code>
                                                    <span className="text-xs text-muted bg-border px-1.5 py-0.5 rounded">
                                                        {propertyFilterCount > 0
                                                            ? `${propertyFilterCount} filter${propertyFilterCount !== 1 ? 's' : ''}`
                                                            : 'No filters yet'}
                                                    </span>
                                                </div>
                                                <div className="text-xs text-muted">
                                                    Show the survey only when this event matches the properties below.
                                                </div>
                                            </div>
                                            <LemonButton
                                                size="xsmall"
                                                icon={<IconX />}
                                                onClick={() => removeTriggerEvent(event.name)}
                                                type="tertiary"
                                            />
                                        </div>
                                        <PropertyFilters
                                            propertyFilters={convertPropertyFiltersToArray(event.propertyFilters)}
                                            onChange={(filters: AnyPropertyFilter[]) =>
                                                updateTriggerEventFilters(event, filters)
                                            }
                                            pageKey={`survey-wizard-event-${event.name}`}
                                            taxonomicGroupTypes={[TaxonomicFilterGroupType.EventProperties]}
                                            excludedProperties={excludedObjectProperties}
                                            eventNames={[event.name]}
                                            buttonText="Add property filter"
                                            buttonSize="small"
                                            operatorAllowlist={SUPPORTED_OPERATORS}
                                        />
                                        <div className="text-xs text-muted mt-2">
                                            Only primitive types are supported here. Array and object properties are
                                            excluded.
                                        </div>
                                    </div>
                                )
                            })}
                        </div>
                    )}
                    <AddEventButton onEventSelect={addTriggerEvent} addButtonText="Add event" />
                    <LemonCheckbox
                        checked={repeatedActivation}
                        onChange={setRepeatedActivation}
                        label="Show every time the event is captured"
                    />
                </div>
            )}

            <div className="border-t border-border pt-6 space-y-2">
                <label className="text-sm font-medium">Delay before showing</label>
                <div className="flex items-center gap-2">
                    <LemonInput
                        type="number"
                        min={0}
                        value={delaySeconds}
                        onChange={(val) => setDelaySeconds(Number(val) || 0)}
                        className="w-20"
                    />
                    <span className="text-secondary text-sm">seconds after conditions are met</span>
                </div>
                <p className="text-muted text-xs">
                    Once a user matches the targeting conditions, wait this long before displaying the survey
                </p>
            </div>
        </div>
    )
}
