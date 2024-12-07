import { IconPlusSmall, IconTrash } from '@posthog/icons'
import { LemonButton, LemonInput, LemonLabel, LemonSelect } from '@posthog/lemon-ui'
import { id } from 'chartjs-plugin-trendline'
import { useValues } from 'kea'
import { PropertyFilters } from 'lib/components/PropertyFilters/PropertyFilters'
import { TaxonomicFilterGroupType } from 'lib/components/TaxonomicFilter/types'
import { TestAccountFilterSwitch } from 'lib/components/TestAccountFiltersSwitch'
import { LemonField } from 'lib/lemon-ui/LemonField'
import React from 'react'
import { ActionFilter } from 'scenes/insights/filters/ActionFilter/ActionFilter'
import { MathAvailability } from 'scenes/insights/filters/ActionFilter/ActionFilterRow/ActionFilterRow'

import { groupsModel } from '~/models/groupsModel'
import { NodeKind } from '~/queries/schema'
import { AnyPropertyFilter, EntityTypes, FilterType, HogFunctionFiltersType } from '~/types'

import { hogFunctionConfigurationLogic } from '../hogFunctionConfigurationLogic'

function sanitizeActionFilters(filters?: FilterType): Partial<HogFunctionFiltersType> {
    if (!filters) {
        return {}
    }
    const sanitized: HogFunctionFiltersType = {}

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

function hogFunctionFiltersToFilters(filters: HogFunctionFiltersType): FilterType {
    // TODO: yuk
    return filters as FilterType
}

const defaultMatchGroupFilters = {
    // TODO: or screen
    events: [{ id: '$pageview', name: '$pageview', type: EntityTypes.EVENTS, order: 0, properties: [] }],
    actions: [],
}

export function HogFunctionFilters(): JSX.Element {
    const { groupsTaxonomicTypes } = useValues(groupsModel)
    const { configuration, type, showSource } = useValues(hogFunctionConfigurationLogic)

    if (type === 'broadcast') {
        return (
            <div className="border bg-bg-light rounded p-3 space-y-2">
                <LemonField name="filters" label="Filters">
                    {({ value, onChange }) => (
                        <PropertyFilters
                            propertyFilters={value?.properties ?? []}
                            taxonomicGroupTypes={[
                                TaxonomicFilterGroupType.PersonProperties,
                                TaxonomicFilterGroupType.Cohorts,
                                TaxonomicFilterGroupType.HogQLExpression,
                            ]}
                            onChange={(properties: AnyPropertyFilter[]) => {
                                onChange({
                                    ...value,
                                    properties,
                                })
                            }}
                            pageKey={`HogFunctionPropertyFilters.${id}`}
                            metadataSource={{ kind: NodeKind.ActorsQuery }}
                        />
                    )}
                </LemonField>
            </div>
        )
    }

    const showMasking = type === 'destination'
    const allowMatchGroups = type === 'site_destination'
    return (
        <div className="border bg-bg-light rounded p-3 space-y-2">
            <LemonField name="filters" label="Filters">
                {({ value, onChange }) => {
                    const filters = (value ?? {}) as HogFunctionFiltersType
                    return (
                        <>
                            <TestAccountFilterSwitch
                                checked={filters?.filter_test_accounts ?? false}
                                onChange={(filter_test_accounts) => onChange({ ...filters, filter_test_accounts })}
                                fullWidth
                            />
                            <PropertyFilters
                                propertyFilters={(filters?.properties ?? []) as AnyPropertyFilter[]}
                                taxonomicGroupTypes={[
                                    TaxonomicFilterGroupType.EventProperties,
                                    TaxonomicFilterGroupType.PersonProperties,
                                    TaxonomicFilterGroupType.EventFeatureFlags,
                                    TaxonomicFilterGroupType.Elements,
                                    TaxonomicFilterGroupType.HogQLExpression,
                                ]}
                                onChange={(properties: AnyPropertyFilter[]) => {
                                    onChange({
                                        ...filters,
                                        properties,
                                    })
                                }}
                                pageKey={`HogFunctionPropertyFilters.${id}`}
                            />
                            <div className="flex w-full gap-2 justify-between">
                                <LemonLabel>Match events and actions</LemonLabel>
                                {showSource && allowMatchGroups ? (
                                    <LemonSelect
                                        value={
                                            filters.matchGroups && filters.matchGroups.length > 0 ? 'match' : 'filters'
                                        }
                                        onChange={(v) => {
                                            if (v === 'filters') {
                                                onChange({ ...filters, matchGroups: null })
                                            } else {
                                                onChange({
                                                    ...filters,
                                                    events: [],
                                                    actions: [],
                                                    matchGroups: [{ key: '', filters: defaultMatchGroupFilters }],
                                                })
                                            }
                                        }}
                                        options={[
                                            {
                                                value: 'filters',
                                                label: 'Simple filters',
                                            },
                                            {
                                                value: 'match',
                                                label: 'Match groups',
                                            },
                                        ]}
                                    />
                                ) : null}
                            </div>
                            {filters.matchGroups && allowMatchGroups ? (
                                <>
                                    <p className="mb-0 text-muted-alt text-xs">
                                        Specify the match group key and its filters. The destination will only run if
                                        any group matches. The matched groups are available under the variable{' '}
                                        <code>matchGroups</code>.
                                    </p>
                                    {filters.matchGroups?.map(({ key, filters: matchFilters }, index) => (
                                        <React.Fragment key={index}>
                                            <div className="flex items-center gap-2">
                                                <LemonLabel>#{index + 1}</LemonLabel>
                                                <LemonInput
                                                    value={key}
                                                    onChange={(e) => {
                                                        onChange({
                                                            ...filters,
                                                            matchGroups: (filters.matchGroups ?? []).map((m, i) =>
                                                                i === index ? { ...m, key: e } : m
                                                            ),
                                                        })
                                                    }}
                                                    placeholder="Match group key"
                                                    fullWidth
                                                />
                                                <LemonButton
                                                    key="delete"
                                                    icon={<IconTrash />}
                                                    title="Delete graph series"
                                                    data-attr={`delete-prop-filter-${index}`}
                                                    onClick={() => {
                                                        onChange({
                                                            ...filters,
                                                            matchGroups: (filters.matchGroups ?? []).filter(
                                                                (_, i) => i !== index
                                                            ),
                                                        })
                                                    }}
                                                />
                                            </div>
                                            <ActionFilter
                                                bordered
                                                filters={hogFunctionFiltersToFilters(matchFilters ?? {})}
                                                setFilters={(f) =>
                                                    onChange({
                                                        ...filters,
                                                        matchGroups: (filters.matchGroups ?? []).map((m, i) =>
                                                            i === index ? { ...m, filters: f } : m
                                                        ),
                                                    })
                                                }
                                                typeKey={`match-group-${index}`}
                                                mathAvailability={MathAvailability.None}
                                                hideRename
                                                hideDuplicate
                                                showNestedArrow={false}
                                                actionsTaxonomicGroupTypes={[
                                                    TaxonomicFilterGroupType.Events,
                                                    TaxonomicFilterGroupType.Actions,
                                                ]}
                                                propertiesTaxonomicGroupTypes={[
                                                    TaxonomicFilterGroupType.EventProperties,
                                                    TaxonomicFilterGroupType.EventFeatureFlags,
                                                    TaxonomicFilterGroupType.Elements,
                                                    TaxonomicFilterGroupType.PersonProperties,
                                                    TaxonomicFilterGroupType.HogQLExpression,
                                                    ...groupsTaxonomicTypes,
                                                ]}
                                                propertyFiltersPopover
                                                addFilterDefaultOptions={{
                                                    id: '$pageview',
                                                    name: '$pageview',
                                                    type: EntityTypes.EVENTS,
                                                }}
                                                buttonCopy="Add event matcher"
                                            />
                                        </React.Fragment>
                                    ))}
                                    <LemonButton
                                        type="tertiary"
                                        data-attr="add-action-event-button"
                                        icon={<IconPlusSmall />}
                                        onClick={() =>
                                            onChange({
                                                ...filters,
                                                matchGroups: [
                                                    ...(filters.matchGroups ?? []),
                                                    { key: '', filters: defaultMatchGroupFilters },
                                                ],
                                            })
                                        }
                                    >
                                        Add match group
                                    </LemonButton>
                                </>
                            ) : (
                                <>
                                    <p className="mb-0 text-muted-alt text-xs">
                                        If set, the destination will only run if the <b>event matches any</b> of the
                                        below.
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
                                        actionsTaxonomicGroupTypes={[
                                            TaxonomicFilterGroupType.Events,
                                            TaxonomicFilterGroupType.Actions,
                                        ]}
                                        propertiesTaxonomicGroupTypes={[
                                            TaxonomicFilterGroupType.EventProperties,
                                            TaxonomicFilterGroupType.EventFeatureFlags,
                                            TaxonomicFilterGroupType.Elements,
                                            TaxonomicFilterGroupType.PersonProperties,
                                            TaxonomicFilterGroupType.HogQLExpression,
                                            ...groupsTaxonomicTypes,
                                        ]}
                                        propertyFiltersPopover
                                        addFilterDefaultOptions={{
                                            id: '$pageview',
                                            name: '$pageview',
                                            type: EntityTypes.EVENTS,
                                        }}
                                        buttonCopy="Add event matcher"
                                    />
                                </>
                            )}
                        </>
                    )
                }}
            </LemonField>
            {showMasking ? (
                <LemonField name="masking" label="Trigger options">
                    {({ value, onChange }) => (
                        <div className="flex items-center gap-1 flex-wrap">
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
                                    <div className="flex items-center gap-1 flex-wrap">
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
                                    <div className="flex items-center gap-1 flex-wrap">
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
