import { useValues } from 'kea'
import { useMemo, useState } from 'react'

import { IconInfo, IconPlus, IconX } from '@posthog/icons'
import { LemonButton, LemonCheckbox, LemonCollapse, LemonInput, LemonSelect, Tooltip } from '@posthog/lemon-ui'

import { EventSelect } from 'lib/components/EventSelect/EventSelect'
import { PropertyFilters } from 'lib/components/PropertyFilters/PropertyFilters'
import { TaxonomicFilterGroupType } from 'lib/components/TaxonomicFilter/types'
import { AddEventButton } from 'scenes/surveys/AddEventButton'
import {
    SUPPORTED_OPERATORS,
    convertArrayToPropertyFilters,
    convertPropertyFiltersToArray,
} from 'scenes/surveys/SurveyEventTrigger'

import { propertyDefinitionsModel } from '~/models/propertyDefinitionsModel'
import {
    ActionType,
    AnyPropertyFilter,
    ProductTourDisplayConditions,
    PropertyType,
    SurveyEventsWithProperties,
} from '~/types'

type TourTriggerType = 'immediate' | 'event' | 'action'

interface AutoShowSectionProps {
    conditions: ProductTourDisplayConditions
    onChange: (conditions: ProductTourDisplayConditions) => void
}

/**
 * this should probably be re-used from surveys!!
 *
 * however, the refactor was more complex than i first thought, esp re: the UI
 * differences. this works, and i want to ship fast
 *
 * i pinky promise i'll be back
 *
 * xoxo,
 * @adboio
 */
function EventTriggerContent({ conditions, onChange }: AutoShowSectionProps): JSX.Element {
    const { propertyDefinitionsByType } = useValues(propertyDefinitionsModel)

    const excludedObjectProperties = useMemo(() => {
        const eventProperties = propertyDefinitionsByType('event')
        const objectProperties = eventProperties.filter((prop) => {
            return !prop.property_type || prop.property_type === PropertyType.StringArray
        })
        return {
            [TaxonomicFilterGroupType.EventProperties]: objectProperties.map((prop) => prop.name),
        }
    }, [propertyDefinitionsByType])

    const events = conditions.events?.values || []

    const updateEventAtIndex = (index: number, updatedEvent: SurveyEventsWithProperties): void => {
        const newEvents = [...events]
        newEvents[index] = updatedEvent
        onChange({
            ...conditions,
            events: { ...conditions.events, values: newEvents },
        })
    }

    const removeEventAtIndex = (index: number): void => {
        const newEvents = events.filter((_, i) => i !== index)
        onChange({
            ...conditions,
            events: newEvents.length > 0 ? { ...conditions.events, values: newEvents } : null,
        })
    }

    return (
        <div className="mt-3 space-y-2">
            {events.length > 0 && (
                <div className="space-y-2">
                    {events.map((event, index) => {
                        const hasPropertyFilters =
                            event.propertyFilters && Object.keys(event.propertyFilters).length > 0

                        return (
                            <LemonCollapse
                                key={`event-${event.name}-${index}`}
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
                                                        updateEventAtIndex(index, {
                                                            ...event,
                                                            propertyFilters: convertArrayToPropertyFilters(filters),
                                                        })
                                                    }}
                                                    pageKey={`tour-event-${event.name}-${index}`}
                                                    taxonomicGroupTypes={[TaxonomicFilterGroupType.EventProperties]}
                                                    excludedProperties={excludedObjectProperties}
                                                    eventNames={[event.name]}
                                                    buttonText="Add property filter"
                                                    buttonSize="small"
                                                    operatorAllowlist={SUPPORTED_OPERATORS}
                                                />
                                                <span className="text-xs text-muted">
                                                    Only primitive types (strings, numbers, booleans) are supported.
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

            <AddEventButton
                onEventSelect={(eventName) => {
                    onChange({
                        ...conditions,
                        events: {
                            ...conditions.events,
                            values: [...events, { name: eventName }],
                        },
                    })
                }}
                excludedEvents={events.map((e) => e.name)}
            />
        </div>
    )
}

export function AutoShowSection({ conditions, onChange }: AutoShowSectionProps): JSX.Element {
    // Derive initial trigger type from conditions
    // this happens again at runtime, so this trigger type is _not_ persisted
    const getInitialTriggerType = (): TourTriggerType => {
        if (conditions.events?.values && conditions.events.values.length > 0) {
            return 'event'
        }
        if (conditions.actions?.values && conditions.actions.values.length > 0) {
            return 'action'
        }
        return 'immediate'
    }

    const [triggerType, setTriggerType] = useState<TourTriggerType>(getInitialTriggerType)

    const handleTriggerTypeChange = (newType: TourTriggerType): void => {
        setTriggerType(newType)
        if (newType === 'immediate') {
            onChange({ ...conditions, events: null, actions: null })
        } else if (newType === 'event') {
            onChange({ ...conditions, actions: null })
        } else if (newType === 'action') {
            onChange({ ...conditions, events: null })
        }
    }

    const triggerOptions = [
        { value: 'immediate' as const, label: 'When the conditions are met' },
        { value: 'event' as const, label: 'When user sends an event' },
        { value: 'action' as const, label: 'When user performs an action' },
    ]

    return (
        <div>
            <h5 className="font-semibold mb-2">
                When to show&nbsp;
                <Tooltip title="Choose when to show the tour to matching users.">
                    <IconInfo />
                </Tooltip>
            </h5>
            <LemonSelect
                value={triggerType}
                onChange={handleTriggerTypeChange}
                options={triggerOptions}
                className="w-full"
            />

            {triggerType === 'event' && <EventTriggerContent conditions={conditions} onChange={onChange} />}

            {triggerType === 'action' && (
                <div className="mt-3">
                    <EventSelect
                        filterGroupTypes={[TaxonomicFilterGroupType.Actions]}
                        onItemChange={(items: ActionType[]) => {
                            onChange({
                                ...conditions,
                                actions:
                                    items.length > 0
                                        ? { values: items.map((e) => ({ id: e.id, name: e.name || '' })) }
                                        : null,
                            })
                        }}
                        selectedItems={conditions.actions?.values || []}
                        selectedEvents={conditions.actions?.values?.map((v) => v.name) ?? []}
                        addElement={
                            <LemonButton size="small" type="secondary" icon={<IconPlus />} sideIcon={null}>
                                Add action
                            </LemonButton>
                        }
                    />
                </div>
            )}

            <div className="flex flex-row gap-2 items-center mt-4">
                <LemonCheckbox
                    checked={!!conditions.autoShowDelaySeconds}
                    onChange={(checked) => {
                        onChange({
                            ...conditions,
                            autoShowDelaySeconds: checked ? 5 : undefined,
                        })
                    }}
                />
                <span className="text-sm">Wait</span>
                <LemonInput
                    type="number"
                    size="small"
                    min={1}
                    max={3600}
                    value={conditions.autoShowDelaySeconds || NaN}
                    onChange={(newValue) => {
                        if (newValue && newValue > 0) {
                            onChange({ ...conditions, autoShowDelaySeconds: newValue })
                        } else {
                            onChange({ ...conditions, autoShowDelaySeconds: undefined })
                        }
                    }}
                    className="w-12"
                />
                <span className="text-sm">seconds before showing the tour after the conditions are met</span>
            </div>
        </div>
    )
}
