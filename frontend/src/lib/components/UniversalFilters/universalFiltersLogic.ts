import { actions, connect, kea, key, listeners, path, props, reducers, selectors } from 'kea'

import {
    createDefaultPropertyFilter,
    PROPERTY_FILTER_TYPE_TO_TAXONOMIC_FILTER_GROUP_TYPE,
    taxonomicFilterTypeToPropertyFilterType,
} from 'lib/components/PropertyFilters/utils'
import {
    hasRecentContext,
    recentTaxonomicFiltersLogic,
} from 'lib/components/TaxonomicFilter/recentTaxonomicFiltersLogic'
import { taxonomicFilterGroupTypeToEntityType } from 'scenes/insights/filters/ActionFilter/ActionFilterRow/ActionFilterRow'
import { sessionRecordingSavedFiltersLogic } from 'scenes/session-recordings/filters/sessionRecordingSavedFiltersLogic'
import { teamLogic } from 'scenes/teamLogic'

import { propertyDefinitionsModel } from '~/models/propertyDefinitionsModel'
import { EntityTypes } from '~/types'
import {
    ActionFilter,
    AnyPropertyFilter,
    EventPropertyFilter,
    FeaturePropertyFilter,
    FilterLogicalOperator,
    PersonPropertyFilter,
    PropertyFilterType,
    PropertyOperator,
    SessionRecordingPlaylistType,
    UniversalFiltersGroup,
    UniversalFiltersGroupValue,
} from '~/types'

import {
    TaxonomicFilterGroup,
    TaxonomicFilterGroupType,
    TaxonomicFilterValue,
    isQuickFilterItem,
    quickFilterToPropertyFilters,
} from '../TaxonomicFilter/types'
import type { universalFiltersLogicType } from './universalFiltersLogicType'

function isApplicableSavedFilter(
    item: unknown
): item is SessionRecordingPlaylistType & { filters: NonNullable<SessionRecordingPlaylistType['filters']> } {
    return typeof item === 'object' && item !== null && 'short_id' in item && 'filters' in item && item.filters != null
}

function recordRecentFromPropertyFilter(propertyFilter: AnyPropertyFilter): void {
    if (!recentTaxonomicFiltersLogic.isMounted()) {
        return
    }
    const key = 'key' in propertyFilter ? propertyFilter.key : undefined
    const filterType = 'type' in propertyFilter ? propertyFilter.type : undefined
    if (!key || !filterType) {
        return
    }
    const groupType = PROPERTY_FILTER_TYPE_TO_TAXONOMIC_FILTER_GROUP_TYPE[filterType]
    if (!groupType) {
        return
    }
    recentTaxonomicFiltersLogic.actions.recordRecentFilter(
        groupType,
        groupType,
        key,
        { name: key },
        teamLogic.values.currentTeamId ?? undefined,
        propertyFilter
    )
}

export const DEFAULT_UNIVERSAL_GROUP_FILTER: UniversalFiltersGroup = {
    type: FilterLogicalOperator.And,
    values: [
        {
            type: FilterLogicalOperator.And,
            values: [],
        },
    ],
}

export type UniversalFiltersLogicProps = {
    rootKey: string
    group: UniversalFiltersGroup | null
    onChange: (group: UniversalFiltersGroup) => void
    taxonomicGroupTypes: TaxonomicFilterGroupType[]
    endpointFilters?: Record<string, any>
}

export const universalFiltersLogic = kea<universalFiltersLogicType>([
    path((key) => ['lib', 'components', 'UniversalFilters', 'universalFiltersLogic', key]),
    props({ endpointFilters: {} } as UniversalFiltersLogicProps),
    key((props) => {
        return `${props.rootKey}-${JSON.stringify(props.group)}`
    }),

    connect(() => ({
        values: [propertyDefinitionsModel, ['describeProperty']],
    })),

    actions({
        addFilterGroup: true,

        setGroupType: (type: FilterLogicalOperator) => ({ type }),
        setGroupValues: (newValues: UniversalFiltersGroupValue[]) => ({ newValues }),
        replaceGroupValue: (index: number, value: UniversalFiltersGroupValue) => ({
            index,
            value,
        }),
        removeGroupValue: (index: number) => ({ index }),

        addGroupFilter: (
            taxonomicGroup: TaxonomicFilterGroup,
            propertyKey: TaxonomicFilterValue,
            item: { propertyFilterType?: PropertyFilterType; name?: string; key?: string }
        ) => ({
            taxonomicGroup,
            propertyKey,
            item,
        }),
    }),

    reducers(({ props }) => ({
        filterGroup: [
            props.group || DEFAULT_UNIVERSAL_GROUP_FILTER,
            {
                setGroupType: (state, { type }) => {
                    return { ...state, type }
                },
                setGroupValues: (state, { newValues }) => {
                    return { ...state, values: newValues }
                },
                replaceGroupValue: (state, { index, value }) => {
                    const newValues = [...state.values]
                    newValues.splice(index, 1, value)
                    return { ...state, values: newValues }
                },
                removeGroupValue: (state, { index }) => {
                    const newValues = [...state.values]
                    newValues.splice(index, 1)
                    return { ...state, values: newValues }
                },
            },
        ],
    })),

    selectors({
        rootKey: [(_, p) => [p.rootKey], (rootKey) => rootKey],
        taxonomicGroupTypes: [(_, p) => [p.taxonomicGroupTypes], (types) => types],
        endpointFilters: [
            (_, p) => [p.endpointFilters || (() => undefined)],
            (endpointFilters?: Record<string, any>) => endpointFilters,
        ],
        taxonomicPropertyFilterGroupTypes: [
            (_, p) => [p.taxonomicGroupTypes],
            (types) =>
                types.filter((t) =>
                    [
                        TaxonomicFilterGroupType.EventProperties,
                        TaxonomicFilterGroupType.PersonProperties,
                        TaxonomicFilterGroupType.EventFeatureFlags,
                        TaxonomicFilterGroupType.Cohorts,
                        TaxonomicFilterGroupType.Elements,
                        TaxonomicFilterGroupType.HogQLExpression,
                        TaxonomicFilterGroupType.FeatureFlags,
                        TaxonomicFilterGroupType.PageviewUrls,
                        TaxonomicFilterGroupType.Screens,
                        TaxonomicFilterGroupType.EmailAddresses,
                        TaxonomicFilterGroupType.Logs,
                        TaxonomicFilterGroupType.LogAttributes,
                        TaxonomicFilterGroupType.LogResourceAttributes,
                    ].includes(t)
                ),
        ],
    }),

    listeners(({ props, values, actions }) => ({
        setGroupType: () => props.onChange(values.filterGroup),
        setGroupValues: () => props.onChange(values.filterGroup),
        replaceGroupValue: ({ value }) => {
            props.onChange(values.filterGroup)
            if (typeof value === 'object' && 'key' in value && 'type' in value && 'value' in value) {
                const filterValue = (value as AnyPropertyFilter).value
                const hasValue = filterValue && !(Array.isArray(filterValue) && filterValue.length === 0)
                if (hasValue) {
                    recordRecentFromPropertyFilter(value as AnyPropertyFilter)
                }
            }
        },
        removeGroupValue: () => props.onChange(values.filterGroup),

        addGroupFilter: ({ taxonomicGroup, propertyKey, item }) => {
            if (taxonomicGroup.type === TaxonomicFilterGroupType.ReplaySavedFilters) {
                if (isApplicableSavedFilter(item)) {
                    sessionRecordingSavedFiltersLogic.findMounted()?.actions.requestApplySavedFilter(item)
                }
                return
            }
            const newValues = [...values.filterGroup.values]

            if (hasRecentContext(item) && item._recentContext.propertyFilter) {
                newValues.push(item._recentContext.propertyFilter)
                recordRecentFromPropertyFilter(item._recentContext.propertyFilter)
                actions.setGroupValues(newValues)
                return
            }

            if (isQuickFilterItem(item)) {
                if (item.eventName) {
                    const eventFilter: ActionFilter = {
                        id: item.eventName,
                        name: item.eventName,
                        type: EntityTypes.EVENTS,
                        properties: quickFilterToPropertyFilters(item),
                    }
                    newValues.push(eventFilter)
                } else {
                    for (const propertyFilter of quickFilterToPropertyFilters(item)) {
                        newValues.push(propertyFilter)
                    }
                }
                actions.setGroupValues(newValues)
                return
            }

            if (
                taxonomicGroup.type === TaxonomicFilterGroupType.PageviewEvents ||
                taxonomicGroup.type === TaxonomicFilterGroupType.PageviewUrls
            ) {
                const urlFilter: EventPropertyFilter = {
                    key: '$current_url',
                    value: propertyKey ? String(propertyKey) : '',
                    operator: PropertyOperator.IContains,
                    type: PropertyFilterType.Event,
                }
                if (taxonomicGroup.type === TaxonomicFilterGroupType.PageviewEvents) {
                    const eventFilter: ActionFilter = {
                        id: '$pageview',
                        name: '$pageview',
                        type: EntityTypes.EVENTS,
                        properties: [urlFilter],
                    }
                    newValues.push(eventFilter)
                } else {
                    newValues.push(urlFilter)
                }
                recordRecentFromPropertyFilter(urlFilter)
                actions.setGroupValues(newValues)
                return
            }

            if (
                taxonomicGroup.type === TaxonomicFilterGroupType.ScreenEvents ||
                taxonomicGroup.type === TaxonomicFilterGroupType.Screens
            ) {
                const screenNameFilter: EventPropertyFilter = {
                    key: '$screen_name',
                    value: propertyKey ? String(propertyKey) : '',
                    operator: PropertyOperator.Exact,
                    type: PropertyFilterType.Event,
                }
                if (taxonomicGroup.type === TaxonomicFilterGroupType.ScreenEvents) {
                    const eventFilter: ActionFilter = {
                        id: '$screen',
                        name: '$screen',
                        type: EntityTypes.EVENTS,
                        properties: [screenNameFilter],
                    }
                    newValues.push(eventFilter)
                } else {
                    newValues.push(screenNameFilter)
                }
                recordRecentFromPropertyFilter(screenNameFilter)
                actions.setGroupValues(newValues)
                return
            }

            if (taxonomicGroup.type === TaxonomicFilterGroupType.AutocaptureEvents) {
                const elTextFilter: EventPropertyFilter = {
                    key: '$el_text',
                    value: propertyKey ? String(propertyKey) : '',
                    operator: PropertyOperator.Exact,
                    type: PropertyFilterType.Event,
                }
                const eventFilter: ActionFilter = {
                    id: '$autocapture',
                    name: '$autocapture',
                    type: EntityTypes.EVENTS,
                    properties: [elTextFilter],
                }
                newValues.push(eventFilter)
                recordRecentFromPropertyFilter(elTextFilter)
                actions.setGroupValues(newValues)
                return
            }

            if (taxonomicGroup.type === TaxonomicFilterGroupType.EmailAddresses) {
                const emailFilter: PersonPropertyFilter = {
                    key: 'email',
                    value: propertyKey ? String(propertyKey) : '',
                    operator: PropertyOperator.Exact,
                    type: PropertyFilterType.Person,
                }
                newValues.push(emailFilter)
                recordRecentFromPropertyFilter(emailFilter)
                actions.setGroupValues(newValues)
                return
            }

            if (taxonomicGroup.type === TaxonomicFilterGroupType.FeatureFlags) {
                if (!item.key) {
                    return
                }
                const newFeatureFlagFilter: FeaturePropertyFilter = {
                    type: PropertyFilterType.Feature,
                    key: item.key,
                    operator: PropertyOperator.Exact,
                }
                newValues.push(newFeatureFlagFilter)
            } else {
                const propertyType =
                    item?.propertyFilterType ?? taxonomicFilterTypeToPropertyFilterType(taxonomicGroup.type)
                if (propertyKey && propertyType) {
                    const newPropertyFilter = createDefaultPropertyFilter(
                        {},
                        propertyKey,
                        propertyType,
                        taxonomicGroup,
                        values.describeProperty
                    )
                    newValues.push(newPropertyFilter)
                } else {
                    const entityType = taxonomicFilterGroupTypeToEntityType(taxonomicGroup.type)
                    if (entityType) {
                        const newEntityFilter: ActionFilter = {
                            id: propertyKey,
                            name: item?.name ?? '',
                            type: entityType,
                        }

                        newValues.push(newEntityFilter)
                    }
                }
            }
            actions.setGroupValues(newValues)
        },
    })),
])
