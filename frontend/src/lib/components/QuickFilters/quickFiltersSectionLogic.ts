import { actions, connect, kea, key, listeners, path, props, reducers } from 'kea'
import { actionToUrl, router, urlToAction } from 'kea-router'
import posthog from 'posthog-js'

import { quickFiltersLogic } from 'lib/components/QuickFilters'

import { QuickFilterContext } from '~/queries/schema/schema-general'
import { PropertyOperator, QuickFilterOption } from '~/types'

import { QuickFiltersEvents } from './consts'
import type { quickFiltersSectionLogicType } from './quickFiltersSectionLogicType'

const QUICK_FILTERS_URL_PARAM = 'quick_filters'

const PAIR_SEPARATOR = ':'
const ENTRY_SEPARATOR = ','

function serializeQuickFilters(selectedFilters: Record<string, SelectedQuickFilter>): string {
    return Object.entries(selectedFilters)
        .map(([filterId, filter]) => `${filterId}${PAIR_SEPARATOR}${filter.optionId}`)
        .join(ENTRY_SEPARATOR)
}

function deserializeQuickFilters(param: string): Record<string, string> {
    const result: Record<string, string> = {}
    if (!param) {
        return result
    }

    for (const entry of param.split(ENTRY_SEPARATOR)) {
        const separatorIndex = entry.indexOf(PAIR_SEPARATOR)
        if (separatorIndex === -1) {
            continue
        }
        const filterId = entry.substring(0, separatorIndex)
        const optionId = entry.substring(separatorIndex + PAIR_SEPARATOR.length)
        if (filterId && optionId) {
            result[filterId] = optionId
        }
    }
    return result
}

export interface SelectedQuickFilter {
    filterId: string
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
        actions: [
            quickFiltersLogic({ context: props.context }),
            ['deleteFilter', 'filterUpdated', 'loadQuickFiltersSuccess'],
        ],
    })),

    actions({
        setQuickFilterValue: (filterId: string, propertyName: string, option: QuickFilterOption) => ({
            filterId,
            propertyName,
            option,
        }),
        clearQuickFilter: (filterId: string) => ({ filterId }),
        restoreFiltersFromUrl: () => ({}),
    }),

    reducers({
        selectedQuickFilters: [
            {} as Record<string, SelectedQuickFilter>,
            {
                setQuickFilterValue: (state, { filterId, propertyName, option }) => ({
                    ...state,
                    [filterId]: {
                        filterId,
                        propertyName,
                        optionId: option.id,
                        value: option.value,
                        operator: option.operator,
                    },
                }),
                clearQuickFilter: (state, { filterId }) => {
                    const newState = { ...state }
                    delete newState[filterId]
                    return newState
                },
            },
        ],
    }),

    listeners(({ actions, values }) => ({
        deleteFilter: ({ id }) => {
            actions.clearQuickFilter(id)
        },
        filterUpdated: ({ filter }) => {
            const currentSelection = values.selectedQuickFilters[filter.id]
            if (!currentSelection) {
                return
            }

            const updatedOption = filter.options.find((o) => o.id === currentSelection.optionId)
            if (updatedOption) {
                actions.setQuickFilterValue(filter.id, filter.property_name, updatedOption)
            } else {
                actions.clearQuickFilter(filter.id)
            }
        },
        setQuickFilterValue: ({ filterId, option }) => {
            const filter = values.quickFilters.find((f) => f.id === filterId)
            posthog.capture(QuickFiltersEvents.QuickFilterSelected, {
                name: filter?.name,
                property_name: filter?.property_name,
                label: option.label,
                value: option.value,
                context: filter?.contexts?.[0],
            })
        },
        loadQuickFiltersSuccess: () => {
            // When quick filters load successfully, restore selections from URL
            actions.restoreFiltersFromUrl()
        },
        restoreFiltersFromUrl: () => {
            const { currentLocation } = router.values
            const quickFiltersParam = currentLocation.searchParams[QUICK_FILTERS_URL_PARAM]
            if (!quickFiltersParam) {
                return
            }

            const urlSelections = deserializeQuickFilters(quickFiltersParam)

            Object.entries(urlSelections).forEach(([filterId, optionId]) => {
                const filter = values.quickFilters.find((f) => f.id === filterId)
                if (!filter) {
                    return
                }

                const option = filter.options.find((o) => o.id === optionId)
                if (!option) {
                    return
                }

                const currentSelection = values.selectedQuickFilters[filterId]
                if (!currentSelection || currentSelection.optionId !== optionId) {
                    actions.setQuickFilterValue(filterId, filter.property_name, option)
                }
            })
        },
    })),

    actionToUrl(({ values }) => {
        const syncFiltersToUrl = (): [string, Record<string, string>, Record<string, any>] => {
            const { currentLocation } = router.values
            const serialized = serializeQuickFilters(values.selectedQuickFilters)

            const newSearchParams = { ...currentLocation.searchParams }
            if (serialized) {
                newSearchParams[QUICK_FILTERS_URL_PARAM] = serialized
            } else {
                delete newSearchParams[QUICK_FILTERS_URL_PARAM]
            }

            return [currentLocation.pathname, newSearchParams, currentLocation.hashParams]
        }
        return {
            setQuickFilterValue: syncFiltersToUrl,
            clearQuickFilter: syncFiltersToUrl,
        }
    }),

    urlToAction(({ actions }) => ({
        '*': (_, searchParams) => {
            // When URL changes, try to restore filters
            if (searchParams[QUICK_FILTERS_URL_PARAM]) {
                actions.restoreFiltersFromUrl()
            }
        },
    })),
])
