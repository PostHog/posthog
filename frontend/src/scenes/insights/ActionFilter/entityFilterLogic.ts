import { kea } from 'kea'
import { actionsModel } from '~/models/actionsModel'
import { EntityTypes, FilterType, Entity, EntityType, ActionFilter, EntityFilter, AnyPropertyFilter } from '~/types'
import { entityFilterLogicType } from './entityFilterLogicType'
import { eventDefinitionsModel } from '~/models/eventDefinitionsModel'
import { eventUsageLogic } from 'lib/utils/eventUsageLogic'

export type LocalFilter = EntityFilter & {
    order: number
    properties?: AnyPropertyFilter[]
}
export type BareEntity = Pick<Entity, 'id' | 'name'>

export function toLocalFilters(filters: FilterType): LocalFilter[] {
    return [
        ...(filters[EntityTypes.ACTIONS] || []),
        ...(filters[EntityTypes.EVENTS] || []),
        ...(filters[EntityTypes.NEW_ENTITY] || []),
    ]
        .sort((a, b) => a.order - b.order)
        .map((filter, order) => ({ ...(filter as EntityFilter), order }))
}

export function toFilters(localFilters: LocalFilter[]): FilterType {
    const filters = localFilters.map((filter, index) => ({
        ...filter,
        order: index,
    }))

    return {
        [EntityTypes.ACTIONS]: filters.filter((filter) => filter.type === EntityTypes.ACTIONS),
        [EntityTypes.EVENTS]: filters.filter((filter) => filter.type === EntityTypes.EVENTS),
        [EntityTypes.NEW_ENTITY]: filters.filter((filter) => filter.type === EntityTypes.NEW_ENTITY),
    } as FilterType
}

export interface EntityFilterProps {
    setFilters: (filters: FilterType) => void
    filters: Record<string, any>
    typeKey: string
    singleMode?: boolean
    addFilterDefaultOptions?: Record<string, any>
}

// required props:
// - filters
// - setFilters
// - typeKey
export const entityFilterLogic = kea<entityFilterLogicType<BareEntity, EntityFilterProps, LocalFilter>>({
    props: {} as EntityFilterProps,
    key: (props) => props.typeKey,
    connect: {
        values: [actionsModel, ['actions']],
    },
    actions: () => ({
        selectFilter: (filter: EntityFilter | ActionFilter | null) => ({ filter }),
        updateFilterMath: (
            filter: Partial<ActionFilter> & {
                index: number
            }
        ) => ({
            type: filter.type as EntityType,
            math: filter.math,
            math_property: filter.math_property,
            index: filter.index,
        }),
        updateFilter: (
            filter: EntityFilter & {
                index: number
            }
        ) => ({
            type: filter.type,
            index: filter.index,
            id: filter.id,
            name: filter.name,
            custom_name: filter.custom_name,
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

    reducers: ({ props }) => ({
        selectedFilter: [
            null as EntityFilter | ActionFilter | null,
            {
                selectFilter: (_, { filter }) => filter,
            },
        ],
        localFilters: [
            toLocalFilters(props.filters ?? {}) as LocalFilter[],
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
    }),

    selectors: {
        entities: [
            (s) => [eventDefinitionsModel.selectors.eventNames, s.actions],
            (
                events,
                actions
            ): {
                [x: string]: ActionFilter[] | BareEntity[]
            } => ({
                [EntityTypes.ACTIONS]: actions,
                [EntityTypes.EVENTS]: events.map((event) => ({ id: event, name: event })),
            }),
        ],
        filters: [(s) => [s.localFilters], (localFilters): FilterType => toFilters(localFilters)],
    },

    listeners: ({ actions, values, props }) => ({
        renameFilter: async ({ custom_name }) => {
            if (!values.selectedFilter) {
                return
            }

            actions.updateFilter({
                ...values.selectedFilter,
                index: values.selectedFilter?.order,
                custom_name,
            } as EntityFilter & {
                index: number
            })
            actions.hideModal()
        },
        hideModal: () => {
            actions.selectFilter(null)
        },
        updateFilter: async ({ type, index, name, id, custom_name }) => {
            actions.setFilters(
                values.localFilters.map((filter, i) =>
                    i === index
                        ? {
                              ...filter,
                              id: id ?? filter.id,
                              name: name ?? filter.name,
                              type: type ?? filter.type,
                              custom_name: custom_name ?? filter.custom_name,
                          }
                        : filter
                )
            )
            !props.singleMode && actions.selectFilter(null)
        },
        updateFilterProperty: async ({ properties, index }) => {
            actions.setFilters(
                values.localFilters.map((filter, i) => (i === index ? { ...filter, properties } : filter))
            )
        },
        updateFilterMath: async ({ math, math_property, index }) => {
            actions.setFilters(
                values.localFilters.map((filter, i) => (i === index ? { ...filter, math, math_property } : filter))
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
            if (values.localFilters.length > 0) {
                const lastFilter: LocalFilter = {
                    ...values.localFilters[previousLength - 1],
                    custom_name: undefined, // Remove custom name
                }
                const order = lastFilter.order + 1
                actions.setFilters([...values.localFilters, { ...lastFilter, order }])
                actions.setEntityFilterVisibility(order, values.entityFilterVisible[lastFilter.order])
            } else {
                actions.setFilters([
                    {
                        id: '$pageview',
                        type: 'events',
                        order: 0,
                        name: '$pageview',
                        ...props.addFilterDefaultOptions,
                    },
                ])
            }
            eventUsageLogic.actions.reportInsightFilterAdded(newLength)
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
    }),
    events: ({ actions, props, values }) => ({
        afterMount: () => {
            if (props.singleMode) {
                const filter = { id: null, name: null, type: EntityTypes.NEW_ENTITY, order: values.localFilters.length }
                actions.setLocalFilters({ [`${EntityTypes.NEW_ENTITY}`]: [filter] })
                actions.selectFilter({ ...filter, index: 0 })
            }
        },
    }),
})
