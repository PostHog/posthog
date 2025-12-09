import { actions, connect, kea, key, listeners, path, props, reducers } from 'kea'
import posthog from 'posthog-js'

import { quickFiltersLogic } from 'lib/components/QuickFilters'

import { QuickFilterContext } from '~/queries/schema/schema-general'
import { PropertyOperator, QuickFilterOption } from '~/types'

import { QuickFiltersEvents } from './consts'
import type { quickFiltersSectionLogicType } from './quickFiltersSectionLogicType'

export interface SelectedQuickFilter {
    propertyName: string
    optionId: string
    value: string | string[] | null
    operator: PropertyOperator
}

export interface QuickFiltersSectionLogicProps {
    context: QuickFilterContext
}

export const quickFiltersSectionLogic = kea<quickFiltersSectionLogicType>([
    path(['lib', 'components', 'QuickFilters', 'quickFiltersSectionLogic']),
    props({} as QuickFiltersSectionLogicProps),
    key((props) => props.context),

    connect((props: QuickFiltersSectionLogicProps) => ({
        values: [quickFiltersLogic({ context: props.context }), ['quickFilters']],
        actions: [quickFiltersLogic({ context: props.context }), ['deleteFilter', 'filterUpdated']],
    })),

    actions({
        setQuickFilterValue: (propertyName: string, option: QuickFilterOption) => ({
            propertyName,
            option,
        }),
        clearQuickFilter: (propertyName: string) => ({ propertyName }),
    }),

    reducers({
        selectedQuickFilters: [
            {} as Record<string, SelectedQuickFilter>,
            {
                setQuickFilterValue: (state, { propertyName, option }) => ({
                    ...state,
                    [propertyName]: {
                        propertyName,
                        optionId: option.id,
                        value: option.value,
                        operator: option.operator,
                    },
                }),
                clearQuickFilter: (state, { propertyName }) => {
                    const newState = { ...state }
                    delete newState[propertyName]
                    return newState
                },
            },
        ],
    }),

    listeners(({ actions, values, props }) => ({
        deleteFilter: ({ id }) => {
            const deletedFilter = values.quickFilters.find((f) => f.id === id)
            if (deletedFilter) {
                actions.clearQuickFilter(deletedFilter.property_name)
            }
        },
        filterUpdated: ({ filter }) => {
            const currentSelection = values.selectedQuickFilters[filter.property_name]
            if (!currentSelection) {
                return
            }

            const updatedOption = filter.options.find((o) => o.id === currentSelection.optionId)
            if (updatedOption) {
                actions.setQuickFilterValue(filter.property_name, updatedOption)
            } else {
                actions.clearQuickFilter(filter.property_name)
            }
        },
        setQuickFilterValue: ({ propertyName, option }) => {
            posthog.capture(QuickFiltersEvents.QuickFilterSelected, {
                name: values.quickFilters.find((f) => f.property_name === propertyName)?.name,
                property_name: propertyName,
                label: option.label,
                value: option.value,
                context: props.context,
            })
        },
    })),
])
