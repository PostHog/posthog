import { LemonBanner, LemonLabel, LemonSelect, LemonSwitch } from '@posthog/lemon-ui'
import { id } from 'chartjs-plugin-trendline'
import clsx from 'clsx'
import { useValues } from 'kea'
import { PropertyFilters } from 'lib/components/PropertyFilters/PropertyFilters'
import { TaxonomicFilterGroupType } from 'lib/components/TaxonomicFilter/types'
import { TestAccountFilterSwitch } from 'lib/components/TestAccountFiltersSwitch'
import { LemonField } from 'lib/lemon-ui/LemonField'
import { ActionFilter } from 'scenes/insights/filters/ActionFilter/ActionFilter'
import { MathAvailability } from 'scenes/insights/filters/ActionFilter/ActionFilterRow/ActionFilterRow'

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

export function HogFunctionFilters({ embedded = false }: { embedded?: boolean }): JSX.Element {
    const { groupsTaxonomicTypes } = useValues(groupsModel)
    const { configuration, type, useMapping, filtersContainPersonProperties } = useValues(hogFunctionConfigurationLogic)

    if (type === 'internal_destination') {
        return <HogFunctionFiltersInternal />
    }

    const isLegacyPlugin = configuration?.template?.id?.startsWith('plugin-')

    const showMasking = type === 'destination' && !isLegacyPlugin
    const showDropEvents = false // TODO coming back to this later for the dropEvents Transformation

    const isTransformation = type === 'transformation'

    return (
        <div
            className={clsx(
                'deprecated-space-y-2 rounded bg-surface-primary',
                !embedded && 'border p-3',
                embedded && 'p-2'
            )}
        >
            <LemonField
                name="filters"
                label={useMapping ? 'Global filters' : 'Filters'}
                info={
                    useMapping
                        ? 'Filters applied to all events before they reach a mapping'
                        : 'Filters applied to all events'
                }
            >
                {({ value, onChange }) => {
                    const filters = (value ?? {}) as CyclotronJobFiltersType
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
                                    checked={filters?.filter_test_accounts ?? false}
                                    onChange={(filter_test_accounts) => onChange({ ...filters, filter_test_accounts })}
                                    fullWidth
                                />
                            )}
                            <PropertyFilters
                                propertyFilters={(filters?.properties ?? []) as AnyPropertyFilter[]}
                                taxonomicGroupTypes={
                                    isTransformation
                                        ? [
                                              TaxonomicFilterGroupType.EventProperties,
                                              TaxonomicFilterGroupType.HogQLExpression,
                                          ]
                                        : [
                                              TaxonomicFilterGroupType.EventProperties,
                                              TaxonomicFilterGroupType.PersonProperties,
                                              TaxonomicFilterGroupType.EventFeatureFlags,
                                              TaxonomicFilterGroupType.Elements,
                                              TaxonomicFilterGroupType.HogQLExpression,
                                              ...groupsTaxonomicTypes,
                                          ]
                                }
                                onChange={(properties: AnyPropertyFilter[]) => {
                                    onChange({
                                        ...filters,
                                        properties,
                                    })
                                }}
                                pageKey={`HogFunctionPropertyFilters.${id}`}
                            />

                            {!useMapping ? (
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
                                        filters={value ?? {} /* TODO: this is any */}
                                        setFilters={(payload) => {
                                            onChange({
                                                ...value,
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
                                        propertiesTaxonomicGroupTypes={
                                            isTransformation
                                                ? [
                                                      TaxonomicFilterGroupType.EventProperties,
                                                      TaxonomicFilterGroupType.HogQLExpression,
                                                  ]
                                                : [
                                                      TaxonomicFilterGroupType.EventProperties,
                                                      TaxonomicFilterGroupType.EventFeatureFlags,
                                                      TaxonomicFilterGroupType.Elements,
                                                      TaxonomicFilterGroupType.PersonProperties,
                                                      TaxonomicFilterGroupType.HogQLExpression,
                                                      ...groupsTaxonomicTypes,
                                                  ]
                                        }
                                        propertyFiltersPopover
                                        addFilterDefaultOptions={{
                                            id: '$pageview',
                                            name: '$pageview',
                                            type: EntityTypes.EVENTS,
                                        }}
                                        buttonCopy="Add event matcher"
                                    />

                                    {showDropEvents && (
                                        <>
                                            <LemonLabel>
                                                <span className="flex flex-1 gap-2 justify-between items-center">
                                                    Drop events that don't match
                                                    <LemonSwitch
                                                        checked={value?.drop_events ?? false}
                                                        onChange={(drop_events) => onChange({ ...value, drop_events })}
                                                    />
                                                </span>
                                            </LemonLabel>

                                            {!value?.drop_events ? (
                                                <p>
                                                    Currently, this will run for all events that match the above
                                                    conditions. Any that do not match will be unmodified and ingested as
                                                    they are.
                                                </p>
                                            ) : (
                                                <LemonBanner type="error">
                                                    This will drop all events that don't match the above conditions.
                                                    Please ensure this is definitely intended.
                                                </LemonBanner>
                                            )}
                                        </>
                                    )}
                                </>
                            ) : null}
                        </>
                    )
                }}
            </LemonField>

            {filtersContainPersonProperties ? (
                <LemonBanner type="warning">
                    You are filtering on Person properties. Be aware that this filtering applies at the time the event
                    is processed so if Person Profiles are not enabled or the person property has not been set by then
                    then the filters may not work as expected.
                </LemonBanner>
            ) : null}
            {showMasking ? (
                <LemonField name="masking" label="Trigger options">
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
}
