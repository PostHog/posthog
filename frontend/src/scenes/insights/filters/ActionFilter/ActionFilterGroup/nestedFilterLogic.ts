import { actions, connect, kea, key, listeners, path, props, reducers, selectors } from 'kea'

import { AnyPropertyFilter } from '~/types'

import { LocalFilter } from '../entityFilterLogic'
import { actionFilterGroupLogic } from './actionFilterGroupLogic'
import type { nestedFilterLogicType } from './nestedFilterLogicType'

export interface NestedFilterLogicProps {
    groupFilterUuid: string
    nestedIndex: number
    typeKey: string
    groupIndex: number
}

/**
 * Minimal logic for nested filters within an ActionFilterGroup.
 * Implements only the actions required by ActionFilterRow and delegates
 * all updates to the parent actionFilterGroupLogic.
 */
export const nestedFilterLogic = kea<nestedFilterLogicType>([
    path(['scenes', 'insights', 'filters', 'ActionFilter', 'ActionFilterGroup', 'nestedFilterLogic']),
    props({} as NestedFilterLogicProps),
    key((props) => `${props.groupFilterUuid}-${props.nestedIndex}`),

    connect((props: NestedFilterLogicProps) => ({
        actions: [
            actionFilterGroupLogic({
                filterUuid: props.groupFilterUuid,
                typeKey: props.typeKey,
                groupIndex: props.groupIndex,
            }),
            ['updateNestedFilter', 'removeNestedFilter', 'updateNestedFilterProperties'],
        ],
    })),

    actions({
        updateFilter: (filter: Partial<LocalFilter> & { index: number }) => ({ filter }),
        removeLocalFilter: (filter: { index: number }) => ({ filter }),
        updateFilterProperty: (filter: { index: number; properties: AnyPropertyFilter[] }) => ({ filter }),
        setEntityFilterVisibility: (index: number, value: boolean) => ({ index, value }),
        // Stub actions that ActionFilterRow may call but we don't need for nested filters
        selectFilter: () => ({}),
        updateFilterOptional: () => ({}),
        updateFilterMath: () => ({}),
        duplicateFilter: () => ({}),
        convertFilterToGroup: () => ({}),
    }),

    reducers({
        filterVisible: [
            false,
            {
                setEntityFilterVisibility: (_, { value }) => value,
            },
        ],
    }),

    selectors({
        entityFilterVisible: [
            (s, p) => [s.filterVisible, p.nestedIndex],
            (filterVisible, nestedIndex): Record<number, boolean> => ({
                [nestedIndex]: filterVisible,
            }),
        ],
    }),

    listeners(({ actions, props }) => ({
        updateFilter: ({ filter }) => {
            actions.updateNestedFilter(props.nestedIndex, filter)
        },
        removeLocalFilter: () => {
            actions.removeNestedFilter(props.nestedIndex)
        },
        updateFilterProperty: ({ filter }) => {
            actions.updateNestedFilterProperties(props.nestedIndex, filter.properties)
        },
    })),
])
