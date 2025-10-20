import { id } from 'chartjs-plugin-trendline'
import clsx from 'clsx'
import { useActions, useValues } from 'kea'
import { useMemo } from 'react'

import { IconCheck, IconX } from '@posthog/icons'
import { LemonBanner, LemonButton, LemonLabel, LemonSelect } from '@posthog/lemon-ui'

import { PropertyFilters } from 'lib/components/PropertyFilters/PropertyFilters'
import { ExcludedProperties, TaxonomicFilterGroupType } from 'lib/components/TaxonomicFilter/types'
import { TestAccountFilterSwitch } from 'lib/components/TestAccountFiltersSwitch'
import { useFeatureFlag } from 'lib/hooks/useFeatureFlag'
import { LemonField } from 'lib/lemon-ui/LemonField'
import { ActionFilter } from 'scenes/insights/filters/ActionFilter/ActionFilter'
import { MathAvailability } from 'scenes/insights/filters/ActionFilter/ActionFilterRow/ActionFilterRow'
import MaxTool from 'scenes/max/MaxTool'

import { groupsModel } from '~/models/groupsModel'
import { AnyPropertyFilter, CyclotronJobFiltersType, EntityTypes, FilterType } from '~/types'

import { hogFunctionConfigurationLogic } from '../configuration/hogFunctionConfigurationLogic'
import { HogFunctionFiltersInternal } from './HogFunctionFiltersInternal'

function sanitizeActionFilters(filters?: FilterType): Partial<CyclotronJobFiltersType> {
    if (!filters) {
        return {}
    }
    const sanitized: CyclotronJobFiltersType = {}

    if (filters.events) {
        sanitized.events = filters.events.map((f) => ({
            id: f.id,
            type: 'events',
            name: f.name,
            order: f.order,
            properties: f.properties,
        }))
    }

    if (filters.actions) {
        sanitized.actions = filters.actions.map((f) => ({
            id: f.id,
            type: 'actions',
            name: f.name,
            order: f.order,
            properties: f.properties,
        }))
    }

    return sanitized
}

export function HogFunctionFilters({
    embedded = false,
    showTriggerOptions = true,
}: {
    embedded?: boolean
    showTriggerOptions?: boolean
}): JSX.Element {
    const { groupsTaxonomicTypes } = useValues(groupsModel)
    const { configuration, type, useMapping, filtersContainPersonProperties, oldFilters, newFilters, isLegacyPlugin } =
        useValues(hogFunctionConfigurationLogic)
    const {
        setOldFilters,
        setNewFilters,
        clearFiltersDiff,
        reportAIFiltersPrompted,
        reportAIFiltersAccepted,
        reportAIFiltersRejected,
        reportAIFiltersPromptOpen,
    } = useActions(hogFunctionConfigurationLogic)

    const isTransformation = type === 'transformation'
    const cdpPersonUpdatesEnabled = useFeatureFlag('CDP_PERSON_UPDATES')

    const excludedProperties: ExcludedProperties = {
        [TaxonomicFilterGroupType.EventProperties]: [
            '$exception_types',
            '$exception_functions',
            '$exception_values',
            '$exception_sources',
            '$exception_list',
            '$exception_type',
            '$exception_level',
            '$exception_message',
        ],
    }

    if (type === 'transformation') {
        excludedProperties[TaxonomicFilterGroupType.Events] = ['$exception']
    }

    const taxonomicGroupTypes = useMemo(() => {
        const types = [
            TaxonomicFilterGroupType.EventProperties,
            TaxonomicFilterGroupType.EventMetadata,
            TaxonomicFilterGroupType.HogQLExpression,
        ]

        if (!isTransformation) {
            types.push(
                TaxonomicFilterGroupType.PersonProperties,
                TaxonomicFilterGroupType.EventFeatureFlags,
                TaxonomicFilterGroupType.Elements,
                ...groupsTaxonomicTypes
            )
        }

        return types
    }, [isTransformation, groupsTaxonomicTypes])

    const showMasking = type === 'destination' && !isLegacyPlugin && showTriggerOptions

    if (type === 'internal_destination') {
        return <HogFunctionFiltersInternal />
    }

    // NOTE: Mappings won't work for person updates currently as they are totally event based...
    const showSourcePicker = cdpPersonUpdatesEnabled && type === 'destination' && !useMapping
    const showEventMatchers = !useMapping && (configuration?.filters?.source ?? 'events') === 'events'

    const mainContent = (
        <div
            className={clsx(
                'deprecated-space-y-2 rounded bg-surface-primary',
                !embedded && 'border p-3',
                embedded && 'p-2'
            )}
        >
            {showSourcePicker && (
                <LemonField
                    name="filters"
                    label="Source"
                    info={
                        <>
                            Select the source of events for the destination.
                            <br />
                            <b>Events</b> will trigger from the real-time stream of ingested events.
                            <br />
                            <b>Person updates</b> will trigger whenever a Person is created, updated or deleted.
                        </>
                    }
                >
                    {({ value, onChange }) => {
                        return (
                            <LemonSelect
                                options={[
                                    { value: 'events', label: 'Events' },
                                    { value: 'person-updates', label: 'Person updates' },
                                ]}
                                value={value?.source ?? 'events'}
                                onChange={(val) => {
                                    onChange({ ...value, source: val })
                                }}
                            />
                        )
                    }}
                </LemonField>
            )}
            <LemonField
                name="filters"
                label={useMapping ? 'Global filters' : 'Filters'}
                info={
                    useMapping
                        ? 'Filters applied to all events before they reach a mapping'
                        : 'Filters applied to all events'
                }
            >
                {({ value, onChange: _onChange }) => {
                    const filters = (value ?? {}) as CyclotronJobFiltersType
                    const currentFilters = newFilters ?? filters

                    const onChange = (newValue: CyclotronJobFiltersType): void => {
                        if (oldFilters && newFilters) {
                            clearFiltersDiff()
                        }
                        _onChange(newValue)
                    }

                    return (
                        <>
                            {useMapping && (
                                <p className="mb-0 text-sm text-secondary">
                                    Filters here apply for all events that could trigger this function, regardless of
                                    mappings.
                                </p>
                            )}
                            {!isTransformation && (
                                <TestAccountFilterSwitch
                                    checked={currentFilters?.filter_test_accounts ?? false}
                                    onChange={(filter_test_accounts) => {
                                        const newValue = { ...currentFilters, filter_test_accounts }
                                        onChange(newValue)
                                    }}
                                    fullWidth
                                />
                            )}
                            <PropertyFilters
                                propertyFilters={(currentFilters?.properties ?? []) as AnyPropertyFilter[]}
                                taxonomicGroupTypes={taxonomicGroupTypes}
                                onChange={(properties: AnyPropertyFilter[]) => {
                                    const newValue = {
                                        ...currentFilters,
                                        properties,
                                    }
                                    onChange(newValue as CyclotronJobFiltersType)
                                }}
                                pageKey={`HogFunctionPropertyFilters.${id}`}
                                excludedProperties={excludedProperties}
                            />

                            {showEventMatchers ? (
                                <>
                                    <div className="flex gap-2 justify-between w-full">
                                        <LemonLabel>
                                            {isTransformation ? 'Match events' : 'Match events and actions'}
                                        </LemonLabel>
                                    </div>
                                    <p className="mb-0 text-xs text-secondary">
                                        If set, the {type} will only run if the <b>event matches any</b> of the below.
                                    </p>
                                    <ActionFilter
                                        bordered
                                        filters={currentFilters ?? {} /* TODO: this is any */}
                                        setFilters={(payload) => {
                                            onChange({
                                                ...currentFilters,
                                                ...sanitizeActionFilters(payload),
                                            })
                                        }}
                                        typeKey="plugin-filters"
                                        mathAvailability={MathAvailability.None}
                                        hideRename
                                        hideDuplicate
                                        showNestedArrow={false}
                                        actionsTaxonomicGroupTypes={
                                            isTransformation
                                                ? [TaxonomicFilterGroupType.Events]
                                                : [TaxonomicFilterGroupType.Events, TaxonomicFilterGroupType.Actions]
                                        }
                                        propertiesTaxonomicGroupTypes={taxonomicGroupTypes}
                                        propertyFiltersPopover
                                        addFilterDefaultOptions={{
                                            id: '$pageview',
                                            name: '$pageview',
                                            type: EntityTypes.EVENTS,
                                        }}
                                        buttonCopy="Add event matcher"
                                        excludedProperties={excludedProperties}
                                    />
                                </>
                            ) : null}
                            {oldFilters && newFilters && (
                                <div className="flex gap-2 items-center p-2 mt-4 rounded border border-dashed bg-surface-secondary">
                                    <div className="flex-1 text-center">
                                        <span className="text-sm font-medium">Suggested by Max</span>
                                    </div>
                                    <div className="flex gap-2">
                                        <LemonButton
                                            status="danger"
                                            icon={<IconX />}
                                            onClick={() => {
                                                onChange(oldFilters)
                                                reportAIFiltersRejected()
                                                clearFiltersDiff()
                                            }}
                                            tooltipPlacement="top"
                                            size="small"
                                        >
                                            Reject
                                        </LemonButton>
                                        <LemonButton
                                            type="tertiary"
                                            icon={<IconCheck color="var(--success)" />}
                                            onClick={() => {
                                                onChange(newFilters)
                                                reportAIFiltersAccepted()
                                                clearFiltersDiff()
                                            }}
                                            tooltipPlacement="top"
                                            size="small"
                                        >
                                            Accept
                                        </LemonButton>
                                    </div>
                                </div>
                            )}
                        </>
                    )
                }}
            </LemonField>

            {filtersContainPersonProperties && showEventMatchers ? (
                <LemonBanner type="warning">
                    You are filtering on Person properties. Be aware that this filtering applies at the time the event
                    is processed so if Person Profiles are not enabled or the person property has not been set by then
                    then the filters may not work as expected.
                </LemonBanner>
            ) : null}
            {showMasking ? (
                <LemonField
                    name="masking"
                    label="Trigger options"
                    info={`
                        You can configure the destination to only run once within a given time interval or until a certain number of events have been processed.
                        This is useful for rate limiting the destination for example if you only want to receive one message per day.
                    `}
                >
                    {({ value, onChange }) => (
                        <div className="flex flex-wrap gap-1 items-center">
                            <LemonSelect
                                options={[
                                    {
                                        value: null,
                                        label: 'Run every time',
                                    },
                                    {
                                        value: 'all',
                                        label: 'Run once per interval',
                                    },
                                    {
                                        value: '{person.id}',
                                        label: 'Run once per person per interval',
                                    },
                                    {
                                        value: '{concat(person.id, event.event)}',
                                        label: 'Run once per person per event name per interval',
                                    },
                                ]}
                                value={value?.hash ?? null}
                                onChange={(val) =>
                                    onChange({
                                        hash: val,
                                        ttl: value?.ttl ?? 60 * 30,
                                    })
                                }
                            />
                            {configuration.masking?.hash ? (
                                <>
                                    <div className="flex flex-wrap gap-1 items-center">
                                        <span>of</span>
                                        <LemonSelect
                                            value={value?.ttl}
                                            onChange={(val) => onChange({ ...value, ttl: val })}
                                            options={[
                                                {
                                                    value: 5 * 60,
                                                    label: '5 minutes',
                                                },
                                                {
                                                    value: 15 * 60,
                                                    label: '15 minutes',
                                                },
                                                {
                                                    value: 30 * 60,
                                                    label: '30 minutes',
                                                },
                                                {
                                                    value: 60 * 60,
                                                    label: '1 hour',
                                                },
                                                {
                                                    value: 2 * 60 * 60,
                                                    label: '2 hours',
                                                },
                                                {
                                                    value: 4 * 60 * 60,
                                                    label: '4 hours',
                                                },
                                                {
                                                    value: 8 * 60 * 60,
                                                    label: '8 hours',
                                                },
                                                {
                                                    value: 12 * 60 * 60,
                                                    label: '12 hours',
                                                },
                                                {
                                                    value: 24 * 60 * 60,
                                                    label: '24 hours',
                                                },
                                            ]}
                                        />
                                    </div>
                                    <div className="flex flex-wrap gap-1 items-center">
                                        <span>or until</span>
                                        <LemonSelect
                                            value={value?.threshold}
                                            onChange={(val) => onChange({ ...value, threshold: val })}
                                            options={[
                                                {
                                                    value: null,
                                                    label: 'Not set',
                                                },
                                                {
                                                    value: 1000,
                                                    label: '1000 events',
                                                },
                                                {
                                                    value: 10000,
                                                    label: '10,000 events',
                                                },
                                                {
                                                    value: 100000,
                                                    label: '100,000 events',
                                                },
                                                {
                                                    value: 1000000,
                                                    label: '1,000,000 events',
                                                },
                                            ]}
                                        />
                                    </div>
                                </>
                            ) : null}
                        </div>
                    )}
                </LemonField>
            ) : null}
        </div>
    )

    return (
        <MaxTool
            identifier="create_hog_function_filters"
            context={{
                current_filters: JSON.stringify(configuration?.filters ?? {}),
                function_type: type,
            }}
            callback={(toolOutput: string) => {
                const parsedFilters = JSON.parse(toolOutput)
                setOldFilters(configuration?.filters ?? {})
                setNewFilters(parsedFilters)
                reportAIFiltersPrompted()
            }}
            onMaxOpen={() => {
                reportAIFiltersPromptOpen()
            }}
            introOverride={{
                headline: 'What events and properties should trigger this function?',
                description: 'Let me help you set up the right filters for your function.',
            }}
        >
            {mainContent}
        </MaxTool>
    )
}
