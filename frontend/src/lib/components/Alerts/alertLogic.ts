import { actions, events, kea, key, listeners, path, props, propsChanged, reducers, selectors } from 'kea'
import { loaders } from 'kea-loaders'

import api from 'lib/api'
import { dayjs } from 'lib/dayjs'
import { formatDate } from 'lib/utils'

import { AlertState } from '~/queries/schema/schema-general'

import type { alertLogicType } from './alertLogicType'
import type { AlertCheck, AlertType } from './types'

export const CHART_CHECKS_LIMIT = 50
export const TABLE_CHECKS_PAGE_SIZE = 25

export interface ChecksHistoryParams {
    limit: number
    offset: number
}

export const DEFAULT_CHECKS_HISTORY_PARAMS: ChecksHistoryParams = {
    limit: TABLE_CHECKS_PAGE_SIZE,
    offset: 0,
}

export interface AlertHistoryChartPoint {
    value: number
    label: string
    /**
     * Whether the check was in a firing state at the time it ran — source of truth for historical firings.
     * Use this instead of re-applying the alert's current thresholds, which may have changed since the check.
     */
    firedAtTime?: boolean
}

export interface AlertLogicProps {
    alertId?: AlertType['id'] | null
    /** `FEATURE_FLAGS.ALERTS_HISTORY_CHART` — drives default checks fetch window; keep in sync wherever `alertLogic` is built. */
    historyChartEnabled: boolean
}

function initialChecksHistoryParams(historyChartEnabled: boolean | undefined): ChecksHistoryParams {
    return {
        limit: historyChartEnabled ? CHART_CHECKS_LIMIT : TABLE_CHECKS_PAGE_SIZE,
        offset: 0,
    }
}

function getCheckPlotValue(check: AlertCheck, isAnomalyDetection: boolean): number | null {
    if (isAnomalyDetection) {
        const scores = check.anomaly_scores
        const lastScore = scores?.length ? scores[scores.length - 1] : null
        if (lastScore != null && !Number.isNaN(lastScore)) {
            return lastScore
        }
    }
    const v = check.calculated_value
    if (v != null && typeof v === 'number' && !Number.isNaN(v)) {
        return v
    }
    return null
}

export const alertLogic = kea<alertLogicType>([
    path(['lib', 'components', 'Alerts', 'alertLogic']),
    props({
        alertId: null,
        historyChartEnabled: false,
    } as AlertLogicProps),
    key(({ alertId }) => alertId ?? 'new'),

    actions({
        setChecksHistoryParams: (limit: number, offset: number) => ({ limit, offset }),
        // Low-level reducer setter — updates `alertHistoryView` only. Prefer `selectAlertHistoryView`
        // from UI code so pagination + checks fetch are reset in the same flow.
        setAlertHistoryView: (view: 'chart' | 'table') => ({ view }),
        setChecksHistoryTablePage: (page: number) => ({ page }),
        // User-facing action: switches view AND re-issues the right checks fetch for the new view.
        selectAlertHistoryView: (view: 'chart' | 'table') => ({ view }),
        alertHistoryTablePageForward: true,
        alertHistoryTablePageBackward: true,
    }),

    reducers(({ props }) => ({
        checksHistoryParams: [
            initialChecksHistoryParams(props.historyChartEnabled),
            {
                setChecksHistoryParams: (_, { limit, offset }) => ({ limit, offset }),
            },
        ],
        alertHistoryView: [
            (props.historyChartEnabled ? 'chart' : 'table') as 'chart' | 'table',
            {
                setAlertHistoryView: (_, { view }) => view,
            },
        ],
        checksHistoryTablePage: [
            1,
            {
                setChecksHistoryTablePage: (_, { page }) => page,
            },
        ],
    })),

    // Loaders must run before `selectors` so `selectors.alert` exists when history selectors are built.
    loaders(({ props, values }) => ({
        alert: [
            null as AlertType | null,
            {
                loadAlert: async () => {
                    if (!props.alertId) {
                        return null
                    }

                    const { limit, offset } = values.checksHistoryParams
                    return await api.alerts.get(props.alertId, { checksLimit: limit, checksOffset: offset })
                },
            },
        ],
    })),

    propsChanged(({ actions, props }, oldProps) => {
        if (!oldProps) {
            return
        }
        const next = !!props.historyChartEnabled
        const prev = !!oldProps.historyChartEnabled
        if (next === prev) {
            return
        }
        actions.setAlertHistoryView(next ? 'chart' : 'table')
        actions.setChecksHistoryTablePage(1)
        actions.setChecksHistoryParams(next ? CHART_CHECKS_LIMIT : TABLE_CHECKS_PAGE_SIZE, 0)
        actions.loadAlert()
    }),

    // Selector deps must be functions from `logic.selectors` / propSelectors — not raw state values.
    selectors(() => ({
        alertHistoryIsAnomalyDetection: [(s) => [s.alert], (alert: AlertType | null) => !!alert?.detector_config],
        alertHistoryChecksSortedDesc: [
            (s) => [s.alert],
            (alert: AlertType | null): AlertCheck[] => {
                const checks = alert?.checks ?? []
                return [...checks].sort((a, b) => dayjs(b.created_at).valueOf() - dayjs(a.created_at).valueOf())
            },
        ],
        alertHistoryChartSeries: [
            (s, p) => [p.historyChartEnabled, s.alert],
            (historyChartEnabled: boolean, alert: AlertType | null): AlertHistoryChartPoint[] => {
                if (!historyChartEnabled || !alert) {
                    return []
                }
                const isAnomaly = !!alert.detector_config
                const sortedAsc = [...(alert.checks ?? [])].sort(
                    (a, b) => dayjs(a.created_at).valueOf() - dayjs(b.created_at).valueOf()
                )
                const points: AlertHistoryChartPoint[] = []
                for (const check of sortedAsc) {
                    const value = getCheckPlotValue(check, isAnomaly)
                    if (value === null) {
                        continue
                    }
                    points.push({
                        value,
                        label: formatDate(dayjs(check.created_at), 'MMM D, HH:mm'),
                        firedAtTime: check.state === AlertState.FIRING,
                    })
                }
                return points
            },
        ],
        alertHistoryUsesAnomalyScores: [
            (s, p) => [p.historyChartEnabled, s.alert],
            (historyChartEnabled: boolean, alert: AlertType | null): boolean => {
                if (!historyChartEnabled || !alert?.detector_config) {
                    return false
                }
                const checks = alert.checks ?? []
                return checks.some((c: AlertCheck) => {
                    const scores = c.anomaly_scores
                    const last = scores?.length ? scores[scores.length - 1] : null
                    return last != null && !Number.isNaN(last)
                })
            },
        ],
        alertHistoryChartSeriesName: [
            (s) => [s.alertHistoryUsesAnomalyScores],
            (usesAnomalyScores: boolean) => (usesAnomalyScores ? 'Anomaly score' : 'Value'),
        ],
        alertHistoryHasHistory: [
            (s) => [s.alert],
            (alert: AlertType | null): boolean => {
                const total = alert?.checks_total
                if (total !== undefined && total > 0) {
                    return true
                }
                return (alert?.checks?.length ?? 0) > 0
            },
        ],
        alertHistoryHasChartableHistory: [
            (s, p) => [s.alertHistoryChartSeries, p.historyChartEnabled],
            (series: AlertHistoryChartPoint[], historyChartEnabled: boolean) =>
                !!historyChartEnabled && series.length > 0,
        ],
        alertHistoryTablePageCount: [
            (s) => [s.alert],
            (alert: AlertType | null): number => {
                const checksTotal = alert?.checks_total
                const resolvedTotal = checksTotal ?? 0
                return Math.max(1, Math.ceil(resolvedTotal / TABLE_CHECKS_PAGE_SIZE) || 1)
            },
        ],
        alertHistoryTableEntryCount: [
            (s) => [s.alert],
            (alert: AlertType | null): number => {
                const resolvedTotal = alert?.checks_total ?? 0
                const checksLen = alert?.checks?.length ?? 0
                return resolvedTotal > 0 ? resolvedTotal : checksLen
            },
        ],
    })),

    listeners(({ actions, values, props }) => ({
        selectAlertHistoryView: ({ view }) => {
            if (!props.historyChartEnabled) {
                return
            }
            actions.setAlertHistoryView(view)
            if (view === 'table') {
                actions.setChecksHistoryTablePage(1)
                actions.setChecksHistoryParams(TABLE_CHECKS_PAGE_SIZE, 0)
            } else {
                actions.setChecksHistoryParams(CHART_CHECKS_LIMIT, 0)
            }
            actions.loadAlert()
        },
        alertHistoryTablePageForward: () => {
            const tablePage = values.checksHistoryTablePage
            if (tablePage >= values.alertHistoryTablePageCount) {
                return
            }
            const next = tablePage + 1
            actions.setChecksHistoryTablePage(next)
            actions.setChecksHistoryParams(TABLE_CHECKS_PAGE_SIZE, (next - 1) * TABLE_CHECKS_PAGE_SIZE)
            actions.loadAlert()
        },
        alertHistoryTablePageBackward: () => {
            const tablePage = values.checksHistoryTablePage
            if (tablePage <= 1) {
                return
            }
            const next = tablePage - 1
            actions.setChecksHistoryTablePage(next)
            actions.setChecksHistoryParams(TABLE_CHECKS_PAGE_SIZE, (next - 1) * TABLE_CHECKS_PAGE_SIZE)
            actions.loadAlert()
        },
    })),

    events(({ actions }) => ({
        afterMount() {
            actions.loadAlert()
        },
    })),
])
