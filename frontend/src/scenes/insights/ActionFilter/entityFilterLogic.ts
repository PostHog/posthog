import { kea } from 'kea'
import { actionsModel } from '~/models/actionsModel'
import {
    EntityTypes,
    FilterType,
    Entity,
    EntityType,
    ActionFilter,
    EntityFilter,
    PropertyFilter,
    ActionType,
} from '~/types'
import { entityFilterLogicType } from './entityFilterLogicType'
import { ActionFilterProps } from './ActionFilter'
import { eventDefinitionsLogic } from 'scenes/events/eventDefinitionsLogic'

export type LocalFilter = EntityFilter & { order: number; properties?: PropertyFilter[] }
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

// required props:
// - filters
// - setFilters
// - typeKey
export const entityFilterLogic = kea<
    entityFilterLogicType<
        FilterType,
        ActionType,
        EntityFilter,
        PropertyFilter,
        ActionFilter,
        EntityType,
        BareEntity,
        LocalFilter
    >
>({
    key: (props) => props.typeKey,
    connect: {
        values: [actionsModel, ['actions']],
    },
    actions: () => ({
        selectFilter: (filter: EntityFilter | ActionFilter | null) => ({ filter }),
        updateFilterMath: (filter: Partial<ActionFilter> & { index: number }) => ({
            type: filter.type,
            math: filter.math,
            math_property: filter.math_property,
            index: filter.index,
        }),
        updateFilter: (filter: EntityFilter & { index: number }) => ({
            type: filter.type,
            index: filter.index,
            id: filter.id,
            name: filter.name,
        }),
        removeLocalFilter: (filter: Partial<EntityFilter> & { index: number }) => ({
            type: filter.type,
            index: filter.index,
        }),
        addFilter: true,
        updateFilterProperty: (filter: Partial<EntityFilter> & { index?: number; properties: PropertyFilter[] }) => ({
            properties: filter.properties,
            index: filter.index,
        }),
        setFilters: (filters: LocalFilter[]) => ({ filters }),
        setLocalFilters: (filters: FilterType) => ({ filters }),
        setEntityFilterVisibility: (index: number, value: boolean) => ({ index, value }),
    }),

    reducers: ({ props }) => ({
        selectedFilter: [
            null as EntityFilter | ActionFilter | null,
            {
                selectFilter: (_state, { filter }) => filter,
            },
        ],
        localFilters: [
            toLocalFilters(((props as any) as ActionFilterProps).filters),
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
    }),

    selectors: {
        entities: [
            (s) => [eventDefinitionsLogic.selectors.eventNames, s.actions],
            (events, actions): { [x: string]: ActionFilter[] | BareEntity[] } => ({
                [EntityTypes.ACTIONS]: actions,
                [EntityTypes.EVENTS]: events.map((event) => ({ id: event, name: event })),
            }),
        ],
        filters: [(s) => [s.localFilters], (localFilters): FilterType => toFilters(localFilters)],
    },

    listeners: ({ actions, values, props }) => ({
        updateFilter: ({ type, index, name, id }) => {
            actions.setFilters(
                values.localFilters.map((filter, i) => (i === index ? { ...filter, id, name, type } : filter))
            )
            !props.singleMode && actions.selectFilter(null)
        },
        updateFilterProperty: ({ properties, index }) => {
            actions.setFilters(
                values.localFilters.map((filter, i) => (i === index ? { ...filter, properties } : filter))
            )
        },
        updateFilterMath: ({ math, math_property, index }) => {
            actions.setFilters(
                values.localFilters.map((filter, i) => (i === index ? { ...filter, math, math_property } : filter))
            )
        },
        removeLocalFilter: ({ index }) => {
            actions.setFilters(values.localFilters.filter((_, i) => i !== index))
        },
        addFilter: () => {
            if (values.localFilters.length > 0) {
                const lastFilter: LocalFilter = values.localFilters[values.localFilters.length - 1]
                const order = lastFilter.order + 1
                actions.setFilters([...values.localFilters, { ...lastFilter, order }])
                actions.setEntityFilterVisibility(order, values.entityFilterVisible[lastFilter.order])
            } else {
                actions.setFilters([
                    {
                        id: null,
                        type: EntityTypes.NEW_ENTITY,
                        order: 0,
                        name: null,
                    },
                ])
            }
        },
        setFilters: ({ filters }) => {
            if (typeof props.setFilters === 'function') {
                props.setFilters(toFilters(filters))
            }
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
