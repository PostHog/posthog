import { actions, kea, key, path, props, reducers, selectors } from 'kea'
import { actionToUrl, router } from 'kea-router'

import { objectsEqual } from 'lib/utils'

import { BreakdownFilter, DashboardFilter, HogQLVariable } from '~/queries/schema/schema-general'
import { AnyPropertyFilter } from '~/types'

import type { dashboardFiltersLogicType } from './dashboardFiltersLogicType'
import {
    MAX_TILES_FOR_AUTOPREVIEW,
    SEARCH_PARAM_FILTERS_KEY,
    combineDashboardFilters,
    encodeURLFilters,
    parseURLFilters,
} from './dashboardUtils'

export interface DashboardFiltersLogicProps {
    id: number
    tileCount?: number
}

export const dashboardFiltersLogic = kea<dashboardFiltersLogicType>([
    path(['scenes', 'dashboard', 'dashboardFiltersLogic']),
    props({} as DashboardFiltersLogicProps),

    key((props) => {
        if (typeof props.id !== 'number') {
            throw Error('Must init dashboardFiltersLogic with a numeric ID key')
        }
        return props.id
    }),

    actions({
        setDates: (dateFrom: string | null, dateTo: string | null | undefined, explicitDate?: boolean) => ({
            dateFrom,
            dateTo,
            explicitDate,
        }),
        setProperties: (properties: AnyPropertyFilter[] | null) => ({ properties }),
        setBreakdownFilter: (breakdownFilter: BreakdownFilter | null) => ({ breakdownFilter }),
        setExternalFilters: (filters: DashboardFilter) => ({ filters }),
        resetIntermittentFilters: true,
        applyFilters: true,
        resetUrlFilters: true,

        setPersistedFilters: (filters: DashboardFilter) => ({ filters }),
        setPersistedVariables: (variables: Record<string, HogQLVariable>) => ({ variables }),
        setTileCount: (tileCount: number) => ({ tileCount }),
    }),

    reducers(({ props }) => ({
        persistedFilters: [
            {} as DashboardFilter,
            {
                setPersistedFilters: (_: DashboardFilter, { filters }: { filters: DashboardFilter }) => filters,
            },
        ],
        persistedVariables: [
            {} as Record<string, HogQLVariable>,
            {
                setPersistedVariables: (
                    _: Record<string, HogQLVariable>,
                    { variables }: { variables: Record<string, HogQLVariable> }
                ) => variables,
            },
        ],
        tileCount: [
            props.tileCount ?? 0,
            {
                setTileCount: (_: number, { tileCount }: { tileCount: number }) => tileCount,
            },
        ],
        externalFilters: [
            {} as DashboardFilter,
            {
                setExternalFilters: (_: DashboardFilter, { filters }: { filters: DashboardFilter }) => filters,
            },
        ],
        intermittentFilters: [
            {
                date_from: undefined,
                date_to: undefined,
                properties: undefined,
                breakdown_filter: undefined,
                explicitDate: undefined,
            } as DashboardFilter,
            {
                setDates: (state, { dateFrom, dateTo, explicitDate }) => ({
                    ...state,
                    date_from: dateFrom,
                    date_to: dateTo,
                    explicitDate,
                }),
                setProperties: (state, { properties }) => ({
                    ...state,
                    properties,
                }),
                setBreakdownFilter: (state, { breakdownFilter }) => ({
                    ...state,
                    breakdown_filter: breakdownFilter,
                }),
                resetIntermittentFilters: () => ({
                    date_from: undefined,
                    date_to: undefined,
                    properties: undefined,
                    breakdown_filter: undefined,
                    explicitDate: undefined,
                }),
            },
        ],
    })),

    selectors(() => ({
        canAutoPreview: [(s) => [s.tileCount], (tileCount) => tileCount < MAX_TILES_FOR_AUTOPREVIEW],
        hasIntermittentFilters: [
            (s) => [s.intermittentFilters],
            (intermittentFilters) => Object.values(intermittentFilters).some((filter) => filter !== undefined),
        ],
        urlFilters: [() => [router.selectors.searchParams], (searchParams) => parseURLFilters(searchParams)],
        hasUrlFilters: [
            (s) => [s.urlFilters],
            (urlFilters) => Object.values(urlFilters).some((filter) => filter !== undefined),
        ],
        showEditBarApplyPopover: [
            (s) => [s.canAutoPreview, s.hasIntermittentFilters],
            (canAutoPreview, hasIntermittentFilters) => !canAutoPreview && hasIntermittentFilters,
        ],
        filtersOverrideForLoad: [
            (s) => [s.externalFilters, s.urlFilters],
            (externalFilters, urlFilters) => combineDashboardFilters(externalFilters, urlFilters),
            { resultEqualityCheck: objectsEqual },
        ],
        effectiveEditBarFilters: [
            (s) => [s.persistedFilters, s.externalFilters, s.urlFilters, s.intermittentFilters],
            (persistedFilters, externalFilters, urlFilters, intermittentFilters) => {
                return combineDashboardFilters(persistedFilters, externalFilters, urlFilters, intermittentFilters)
            },
            { resultEqualityCheck: objectsEqual },
        ],
        effectiveRefreshFilters: [
            (s) => [s.persistedFilters, s.externalFilters, s.urlFilters],
            (persistedFilters, externalFilters, urlFilters): DashboardFilter => {
                return combineDashboardFilters(persistedFilters, externalFilters, urlFilters)
            },
            { resultEqualityCheck: objectsEqual },
        ],
        effectiveDashboardVariableOverrides: [
            (s) => [s.persistedVariables],
            (persistedVariables) => ({ ...persistedVariables }),
            { resultEqualityCheck: objectsEqual },
        ],
    })),

    actionToUrl(({ values }) => ({
        applyFilters: () => {
            const { currentLocation } = router.values

            const urlFilters = parseURLFilters(currentLocation.searchParams)
            const newUrlFilters: DashboardFilter = combineDashboardFilters(urlFilters, values.intermittentFilters)

            const newSearchParams = {
                ...currentLocation.searchParams,
            }

            return [
                currentLocation.pathname,
                { ...newSearchParams, ...encodeURLFilters(newUrlFilters) },
                currentLocation.hashParams,
            ]
        },
        setProperties: ({ properties }) => {
            if (!values.canAutoPreview) {
                return
            }

            const { currentLocation } = router.values

            const urlFilters = parseURLFilters(currentLocation.searchParams)
            const newUrlFilters: DashboardFilter = {
                ...urlFilters,
                properties,
            }

            const newSearchParams = {
                ...currentLocation.searchParams,
            }

            return [
                currentLocation.pathname,
                { ...newSearchParams, ...encodeURLFilters(newUrlFilters) },
                currentLocation.hashParams,
            ]
        },
        setDates: ({ dateFrom, dateTo }) => {
            if (!values.canAutoPreview) {
                return
            }

            const { currentLocation } = router.values

            const urlFilters = parseURLFilters(currentLocation.searchParams)
            const newUrlFilters: DashboardFilter = {
                ...urlFilters,
                date_from: dateFrom,
                date_to: dateTo,
                explicitDate: values.intermittentFilters.explicitDate,
            }

            const newSearchParams = {
                ...currentLocation.searchParams,
            }

            return [
                currentLocation.pathname,
                { ...newSearchParams, ...encodeURLFilters(newUrlFilters) },
                currentLocation.hashParams,
            ]
        },
        setBreakdownFilter: ({ breakdownFilter }) => {
            if (!values.canAutoPreview) {
                return
            }

            const { currentLocation } = router.values

            const urlFilters = parseURLFilters(currentLocation.searchParams)
            const newUrlFilters: DashboardFilter = {
                ...urlFilters,
                breakdown_filter: breakdownFilter,
            }

            const newSearchParams = {
                ...currentLocation.searchParams,
            }

            return [
                currentLocation.pathname,
                { ...newSearchParams, ...encodeURLFilters(newUrlFilters) },
                currentLocation.hashParams,
            ]
        },
        resetUrlFilters: () => {
            const { currentLocation } = router.values
            const newSearchParams = { ...currentLocation.searchParams }
            delete newSearchParams[SEARCH_PARAM_FILTERS_KEY]
            return [currentLocation.pathname, newSearchParams, currentLocation.hashParams]
        },
    })),
])
