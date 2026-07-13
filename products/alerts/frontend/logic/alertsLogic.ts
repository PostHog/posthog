import { actions, afterMount, kea, listeners, path, reducers, selectors } from 'kea'
import { loaders } from 'kea-loaders'

import { PaginationManual } from '@posthog/lemon-ui'

import api from 'lib/api'
import { objectClean } from 'lib/utils/objects'

import { AlertState } from '~/queries/schema/schema-general'

import { AlertType } from '../types'
import { AlertLogicProps } from './alertLogic'
import type { alertsLogicType } from './alertsLogicType'

export interface AlertsLogicProps extends AlertLogicProps {}

export const ALERTS_PER_PAGE = 30

export interface AlertsFilters {
    search: string
    createdBy: string
}

export const DEFAULT_ALERTS_FILTERS: AlertsFilters = {
    search: '',
    createdBy: 'All users',
}

export const alertsLogic = kea<alertsLogicType>([
    path(['lib', 'components', 'Alerts', 'alertsLogic']),

    actions({
        setPage: (page: number) => ({ page }),
        setFilters: (filters: Partial<AlertsFilters>) => ({ filters }),
    }),

    reducers({
        page: [
            1,
            {
                setPage: (_, { page }) => page,
            },
        ],
        filters: [
            DEFAULT_ALERTS_FILTERS,
            {
                setFilters: (state, { filters }) =>
                    objectClean({
                        ...state,
                        ...filters,
                    }),
            },
        ],
    }),

    loaders(({ values }) => ({
        alertsResponse: [
            { results: [], count: 0 } as { results: AlertType[]; count: number },
            {
                loadAlerts: async () => {
                    const search = values.filters.search.trim()

                    const response = await api.alerts.list(undefined, {
                        limit: ALERTS_PER_PAGE,
                        offset: (values.page - 1) * ALERTS_PER_PAGE,
                        ...(search ? { search } : {}),
                        ...(values.filters.createdBy !== 'All users' ? { created_by: values.filters.createdBy } : {}),
                    })
                    return { results: response.results, count: response.count ?? response.results.length }
                },
            },
        ],
    })),

    selectors(({ actions }) => ({
        alerts: [(s) => [s.alertsResponse], (response): AlertType[] => response.results],
        alertsCount: [(s) => [s.alertsResponse], (response): number => response.count],
        isFiltering: [
            (s) => [s.filters],
            (filters): boolean =>
                filters.search !== DEFAULT_ALERTS_FILTERS.search ||
                filters.createdBy !== DEFAULT_ALERTS_FILTERS.createdBy,
        ],
        alertsSortedByState: [
            (s) => [s.alerts],
            (alerts: AlertType[]): AlertType[] =>
                [...alerts].sort((a, b) => alertComparatorKey(a) - alertComparatorKey(b)),
        ],
        pagination: [
            (s) => [s.page, s.alertsCount],
            (page, count): PaginationManual => ({
                controlled: true,
                pageSize: ALERTS_PER_PAGE,
                currentPage: page,
                entryCount: count,
                onBackward: () => actions.setPage(page - 1),
                onForward: () => actions.setPage(page + 1),
            }),
        ],
    })),

    listeners(({ actions, values }) => ({
        setPage: () => {
            actions.loadAlerts()
        },
        setFilters: async ({ filters }, breakpoint) => {
            if ('search' in filters && filters.search?.trim()) {
                await breakpoint(300)
            }
            if (values.page !== 1) {
                actions.setPage(1)
            } else {
                actions.loadAlerts()
            }
        },
    })),

    afterMount(({ actions }) => actions.loadAlerts()),
])

const alertComparatorKey = (alert: AlertType): number => {
    if (!alert.enabled) {
        return 100
    }

    switch (alert.state) {
        case AlertState.FIRING:
            return 1
        case AlertState.ERRORED:
            return 2
        case AlertState.SNOOZED:
            return 3
        case AlertState.NOT_FIRING:
            return 4
    }
}
