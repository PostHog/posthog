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
    logicKey?: string
}

const applyQuickFilter = (
    state: Record<string, SelectedQuickFilter>,
    { filterId, propertyName, option }: { filterId: string; propertyName: string; option: QuickFilterOption }
): Record<string, SelectedQuickFilter> => ({
    ...state,
    [filterId]: {
        filterId,
        propertyName,
        optionId: option.id,
        value: option.value,
        operator: option.operator,
    },
})

const removeQuickFilter = (
    state: Record<string, SelectedQuickFilter>,
    { filterId }: { filterId: string }
): Record<string, SelectedQuickFilter> => {
    const newState = { ...state }
    delete newState[filterId]
    return newState
}

export const quickFiltersSectionLogic = kea<quickFiltersSectionLogicType>([
    path(['lib', 'components', 'QuickFilters', 'quickFiltersSectionLogic']),
    props({} as QuickFiltersSectionLogicProps),
    key((props) => (props.logicKey ? `${props.context}-${props.logicKey}` : props.context)),

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
        /** Internal action for URL restoration -- updates state without firing analytics */
        restoreQuickFilterValue: (filterId: string, propertyName: string, option: QuickFilterOption) => ({
            filterId,
            propertyName,
            option,
        }),
        clearQuickFilter: (filterId: string) => ({ filterId }),
        /** Internal action for URL restoration (clears state without firing committed signal, see: actionToUrl) */
        restoreClearQuickFilter: (filterId: string) => ({ filterId }),
        restoreFiltersFromUrl: () => ({}),
        quickFiltersChanged: true,
        quickFiltersCommitted: true,
        /** Fires after initial URL restoration completes, regardless of whether state changed */
        quickFiltersUrlRestoreComplete: true,
    }),

    reducers({
        selectedQuickFilters: [
            {} as Record<string, SelectedQuickFilter>,
            {
                setQuickFilterValue: applyQuickFilter,
                restoreQuickFilterValue: applyQuickFilter,
                clearQuickFilter: removeQuickFilter,
                restoreClearQuickFilter: removeQuickFilter,
            },
        ],
    }),

    listeners(({ actions, values, props }) => ({
        deleteFilter: ({ id }) => {
            actions.clearQuickFilter(id)
        },
        clearQuickFilter: () => {
            actions.quickFiltersChanged()
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
                context: props.context,
            })
            actions.quickFiltersChanged()
        },
        quickFiltersChanged: () => {
            actions.quickFiltersCommitted()
        },
        loadQuickFiltersSuccess: () => {
            // When quick filters load successfully, restore selections from URL
            actions.restoreFiltersFromUrl()
        },
        restoreFiltersFromUrl: () => {
            const { currentLocation } = router.values
            const quickFiltersParam = currentLocation.searchParams[QUICK_FILTERS_URL_PARAM]
            const urlSelections = quickFiltersParam ? deserializeQuickFilters(quickFiltersParam) : {}
            let didChange = false

            // Add/update selections that are in URL but not (or different) in state
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
                    actions.restoreQuickFilterValue(filterId, filter.property_name, option)
                    didChange = true
                }
            })

            // Clear selections that are in state but not in URL
            Object.keys(values.selectedQuickFilters).forEach((filterId) => {
                if (!urlSelections[filterId]) {
                    actions.restoreClearQuickFilter(filterId)
                    didChange = true
                }
            })

            if (didChange) {
                actions.quickFiltersCommitted()
            }
            actions.quickFiltersUrlRestoreComplete()
        },
    })),

    // Two-way URL sync: actionToUrl writes state -> URL, urlToAction restores URL -> state.
    // Guards in restoreFiltersFromUrl prevent infinite loops (no-op when state matches URL).
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
        const replaceFiltersInUrl = (): [string, Record<string, string>, Record<string, any>, { replace: true }] => {
            const [pathname, searchParams, hashParams] = syncFiltersToUrl()
            return [pathname, searchParams, hashParams, { replace: true }]
        }
        return {
            setQuickFilterValue: syncFiltersToUrl,
            restoreQuickFilterValue: replaceFiltersInUrl,
            restoreClearQuickFilter: replaceFiltersInUrl,
            clearQuickFilter: syncFiltersToUrl,
        }
    }),

    urlToAction(({ actions, cache }) => ({
        '*': () => {
            const param = router.values.currentLocation.searchParams[QUICK_FILTERS_URL_PARAM] ?? ''
            if (param === cache.lastQuickFiltersParam) {
                return
            }
            cache.lastQuickFiltersParam = param
            actions.restoreFiltersFromUrl()
        },
    })),
])
