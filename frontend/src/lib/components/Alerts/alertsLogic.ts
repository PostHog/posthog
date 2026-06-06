import { actions, afterMount, kea, listeners, path, reducers, selectors } from 'kea'
import { loaders } from 'kea-loaders'

import { PaginationManual } from '@posthog/lemon-ui'

import api from 'lib/api'

import { AlertState } from '~/queries/schema/schema-general'

import { AlertLogicProps } from './alertLogic'
import type { alertsLogicType } from './alertsLogicType'
import { AlertType } from './types'

export interface AlertsLogicProps extends AlertLogicProps {}

export const ALERTS_PER_PAGE = 30

export const alertsLogic = kea<alertsLogicType>([
    path(['lib', 'components', 'Alerts', 'alertsLogic']),

    actions({
        setPage: (page: number) => ({ page }),
    }),

    reducers({
        page: [
            1,
            {
                setPage: (_, { page }) => page,
            },
        ],
    }),

    loaders(({ values }) => ({
        alertsResponse: [
            { results: [], count: 0 } as { results: AlertType[]; count: number },
            {
                loadAlerts: async () => {
                    const response = await api.alerts.list(undefined, {
                        limit: ALERTS_PER_PAGE,
                        offset: (values.page - 1) * ALERTS_PER_PAGE,
                    })
                    return { results: response.results, count: response.count ?? response.results.length }
                },
            },
        ],
    })),

    selectors(({ actions }) => ({
        alerts: [(s) => [s.alertsResponse], (response): AlertType[] => response.results],
        alertsCount: [(s) => [s.alertsResponse], (response): number => response.count],
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

    listeners(({ actions }) => ({
        setPage: () => {
            actions.loadAlerts()
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
