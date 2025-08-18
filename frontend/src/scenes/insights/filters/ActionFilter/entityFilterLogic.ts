import { actions, connect, events, kea, key, listeners, path, props, reducers, selectors } from 'kea'

import { convertPropertyGroupToProperties } from 'lib/components/PropertyFilters/utils'
import { defaultDataWarehousePopoverFields } from 'lib/components/TaxonomicFilter/taxonomicFilterLogic'
import { DataWarehousePopoverField } from 'lib/components/TaxonomicFilter/types'
import { uuid } from 'lib/utils'
import { GraphSeriesAddedSource, eventUsageLogic } from 'lib/utils/eventUsageLogic'
import { getDefaultEventLabel, getDefaultEventName } from 'lib/utils/getAppContext'
import { insightDataLogic } from 'scenes/insights/insightDataLogic'

import {
    ActionFilter,
    AnyPropertyFilter,
    DataWarehouseFilter,
    Entity,
    EntityFilter,
    EntityType,
    EntityTypes,
    FilterType,
} from '~/types'

import type { entityFilterLogicType } from './entityFilterLogicType'

export type LocalFilter = ActionFilter & {
    order: number
    uuid: string
    table_name?: string
    [key: string]: any
}

export type BareEntity = Pick<Entity, 'id' | 'name'>

export function toLocalFilters(filters: Partial<FilterType>): LocalFilter[] {
    const localFilters = [
        ...(filters[EntityTypes.ACTIONS] || []),
        ...(filters[EntityTypes.EVENTS] || []),
        ...(filters[EntityTypes.DATA_WAREHOUSE] || []),
    ]
        .sort((a, b) => a.order - b.order)
        .map((filter, order) => ({ ...(filter as ActionFilter), order }))
    return localFilters.map((filter) =>
        filter.properties && Array.isArray(filter.properties)
            ? {
                  ...filter,
                  uuid: uuid(),
                  properties: convertPropertyGroupToProperties(filter.properties),
              }
            : { ...filter, uuid: uuid() }
    )
}

export function toFilters(localFilters: LocalFilter[]): FilterType {
    const filters = localFilters.map((filter, index) => ({
        ...filter,
        order: index,
        // The first step of a funnel cannot be optional
        optionalInFunnel: index == 0 ? undefined : filter.optionalInFunnel,
    }))

    return {
        [EntityTypes.ACTIONS]: filters.filter((filter) => filter.type === EntityTypes.ACTIONS),
        [EntityTypes.EVENTS]: filters.filter((filter) => filter.type === EntityTypes.EVENTS),
        [EntityTypes.DATA_WAREHOUSE]: filters.filter((filter) => filter.type === EntityTypes.DATA_WAREHOUSE),
    } as FilterType
}

export interface EntityFilterProps {
    setFilters?: (filters: FilterType) => void
    filters?: Record<string, any>
    typeKey: string
    singleMode?: boolean
    addFilterDefaultOptions?: Record<string, any>
    dataWarehousePopoverFields?: DataWarehousePopoverField[]
}

export const entityFilterLogic = kea<entityFilterLogicType>([
    props({} as EntityFilterProps),
    key((props) => props.typeKey),
    path((key) => ['scenes', 'insights', 'ActionFilter', 'entityFilterLogic', key]),
    connect(() => ({
        logic: [eventUsageLogic],
    })),
    actions({
        selectFilter: (filter: EntityFilter | ActionFilter | null) => ({ filter }),
        updateFilterMath: (
            filter: Partial<ActionFilter> & {
                index: number
            }
        ) => ({
            type: filter.type as EntityType,
            math: filter.math,
            math_property: filter.math_property,
            math_property_type: filter.math_property_type,
            math_hogql: filter.math_hogql,
            index: filter.index,
            math_group_type_index: filter.math_group_type_index,
        }),
        updateFilterOptional: (
            filter: Partial<ActionFilter> & {
                index: number
            }
        ) => ({
            type: filter.type as EntityType,
            index: filter.index,
            optionalInFunnel: filter.optionalInFunnel,
        }),
        updateFilter: (
            filter: (EntityFilter | ActionFilter | DataWarehouseFilter) & {
                index: number
                table_name?: string
                [key: string]: any
            }
        ) => ({
            ...filter,
        }),
        renameFilter: (custom_name: string) => ({ custom_name }),
        removeLocalFilter: (
            filter: Partial<EntityFilter> & {
                index: number
            }
        ) => ({
            type: filter.type,
            index: filter.index,
        }),
        addFilter: true,
        duplicateFilter: (filter: EntityFilter | ActionFilter) => ({ filter }),
        updateFilterProperty: (
            filter: Partial<EntityFilter> & {
                index?: number
                properties: AnyPropertyFilter[]
            }
        ) => ({
            properties: filter.properties,
            index: filter.index,
        }),
        setFilters: (filters: LocalFilter[]) => ({ filters }),
        setLocalFilters: (filters: FilterType) => ({ filters }),
        setEntityFilterVisibility: (index: number, value: boolean) => ({ index, value }),
        renameLocalFilter: (index: number, custom_name: string) => ({ index, custom_name }),
        showModal: true,
        hideModal: true,
    }),

    reducers(({ props }) => ({
        selectedFilter: [
            null as EntityFilter | ActionFilter | null,
            {
                selectFilter: (_, { filter }) => filter,
            },
        ],
        localFilters: [
            toLocalFilters(props.filters ?? {}),
            {
                setLocalFilters: (_, { filters }) => toLocalFilters(filters),
            },
        ],
        entityFilterVisible: [
            [] as boolean[],
            {
                setEntityFilterVisibility: (state, { index, value }) => ({
                    ...state,
                    [index]: value,
                }),
            },
        ],
        modalVisible: [
            false,
            {
                showModal: () => true,
                hideModal: () => false,
            },
        ],
    })),

    selectors({
        filters: [(s) => [s.localFilters], (localFilters): FilterType => toFilters(localFilters)],
    }),

    listeners(({ actions, values, props }) => ({
        renameFilter: async ({ custom_name }, breakpoint) => {
            if (!values.selectedFilter) {
                return
            }

            await breakpoint(100)

            actions.updateFilter({
                ...values.selectedFilter,
                index: values.selectedFilter?.order,
                custom_name,
            } as EntityFilter & {
                index: number
            })
            actions.hideModal()

            await breakpoint(100)

            const dataLogic = insightDataLogic.findMounted({
                dashboardItemId: props.typeKey,
            })
            dataLogic?.actions?.loadData('force_async')
        },
        hideModal: () => {
            actions.selectFilter(null)
        },
        updateFilter: async ({ type, index, name, id, custom_name, table_name, ...fieldValues }) => {
            actions.setFilters(
                values.localFilters.map((filter, i) => {
                    if (i === index) {
                        const dataWarehousePopoverFields =
                            props.dataWarehousePopoverFields ?? defaultDataWarehousePopoverFields
                        if (type === EntityTypes.DATA_WAREHOUSE) {
                            const updatedFilter = {
                                ...filter,
                                id: typeof id === 'undefined' ? filter.id : id,
                                name: typeof name === 'undefined' ? filter.name : name,
                                type: typeof type === 'undefined' ? filter.type : type,
                                custom_name: typeof custom_name === 'undefined' ? filter.custom_name : custom_name,
                                table_name: typeof table_name === 'undefined' ? filter.table_name : table_name,
                            }

                            // Dynamically handle fields from dataWarehousePopoverFields
                            dataWarehousePopoverFields.forEach(({ key }) => {
                                const fieldValue = fieldValues[key]
                                updatedFilter[key] = typeof fieldValue === 'undefined' ? filter[key] : fieldValue
                            })

                            return updatedFilter
                        }

                        // For non-DATA_WAREHOUSE types, remove any data warehouse specific fields
                        const cleanedFilter = { ...filter }
                        dataWarehousePopoverFields.forEach(({ key }) => {
                            delete cleanedFilter[key]
                        })

                        return {
                            ...cleanedFilter,
                            id: typeof id === 'undefined' ? filter.id : id,
                            name: typeof name === 'undefined' ? filter.name : name,
                            type: typeof type === 'undefined' ? filter.type : type,
                            custom_name: typeof custom_name === 'undefined' ? filter.custom_name : custom_name,
                        }
                    }

                    return filter
                })
            )
            !props.singleMode && actions.selectFilter(null)
        },
        updateFilterProperty: async ({ properties, index }) => {
            actions.setFilters(
                values.localFilters.map((filter, i) => (i === index ? { ...filter, properties } : filter))
            )
        },
        updateFilterMath: async ({ index, ...mathProperties }) => {
            actions.setFilters(
                values.localFilters.map((filter, i) => (i === index ? { ...filter, ...mathProperties } : filter))
            )
        },
        updateFilterOptional: async ({ index, optionalInFunnel }) => {
            actions.setFilters(
                values.localFilters.map((filter, i) => (i === index ? { ...filter, optionalInFunnel } : filter))
            )
        },
        removeLocalFilter: async ({ index }) => {
            const newFilters = values.localFilters.filter((_, i) => i !== index)
            actions.setFilters(newFilters)
            actions.setLocalFilters(toFilters(newFilters))
            eventUsageLogic.actions.reportInsightFilterRemoved(index)
        },
        addFilter: async () => {
            const previousLength = values.localFilters.length
            const newLength = previousLength + 1
            const precedingEntity = values.localFilters[previousLength - 1] as LocalFilter | undefined
            const order = precedingEntity ? precedingEntity.order + 1 : 0
            const newFilter: LocalFilter = {
                id: getDefaultEventName(),
                name: getDefaultEventLabel(),
                uuid: uuid(),
                type: EntityTypes.EVENTS,
                order: order,
                ...props.addFilterDefaultOptions,
            }
            actions.setFilters([...values.localFilters, newFilter])
            actions.selectFilter({ ...newFilter, index: order })
            eventUsageLogic.actions.reportInsightFilterAdded(newLength, GraphSeriesAddedSource.Default)
        },
        duplicateFilter: async ({ filter }) => {
            const previousLength = values.localFilters.length
            const newLength = previousLength + 1
            const order = filter.order ?? values.localFilters[previousLength - 1].order
            const newFilters = [...values.localFilters]
            for (const _filter of newFilters) {
                // Because duplicate filters are inserted within the current filters we need to move over the remaining filers
                if (_filter.order >= order + 1) {
                    _filter.order = _filter.order + 1
                }
            }
            newFilters.splice(order + 1, 0, {
                ...filter,
                uuid: uuid(),
                custom_name: undefined,
                order: order + 1,
            } as LocalFilter)
            actions.setFilters(newFilters)
            actions.setEntityFilterVisibility(order + 1, values.entityFilterVisible[order])
            eventUsageLogic.actions.reportInsightFilterAdded(newLength, GraphSeriesAddedSource.Duplicate)
        },
        setFilters: async ({ filters }) => {
            if (typeof props.setFilters === 'function') {
                props.setFilters(toFilters(filters))
            }
            const sanitizedFilters = filters?.map(({ id, type }) => ({ id, type }))
            eventUsageLogic.actions.reportInsightFilterSet(sanitizedFilters)
        },
        setEntityFilterVisibility: async ({ index, value }) => {
            eventUsageLogic.actions.reportEntityFilterVisibilitySet(index, value)
        },
    })),
    events(({ actions, props, values }) => ({
        afterMount: () => {
            if (props.singleMode) {
                const filter = { id: null, type: EntityTypes.EVENTS, order: values.localFilters.length }
                actions.setLocalFilters({ [`${EntityTypes.EVENTS}`]: [filter] })
                actions.selectFilter({ ...filter, index: 0 })
            }
        },
    })),
])
