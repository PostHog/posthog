import posthog from 'posthog-js'
import { useCallback, useEffect, useRef, useState } from 'react'

import { buildAlertFilterConfig } from 'lib/utils/alertUtils'

import { AlertType } from '~/lib/components/Alerts/types'
import { DashboardType, HogFunctionType, InsightModel, QueryBasedInsightModel } from '~/types'

import api from '../../api'
import { DashboardExportResult, generateDashboardHCL } from './dashboardHclExporter'
import { InsightExportResult, generateInsightHCL } from './insightHclExporter'

export type TerraformExportResult = DashboardExportResult | InsightExportResult

export type TerraformExportResource =
    | { type: 'insight'; data: Partial<InsightModel> }
    | { type: 'dashboard'; data: DashboardType<QueryBasedInsightModel> }

export interface TerraformExportState {
    loading: boolean
    error: string | null
    result: TerraformExportResult | null
}

async function fetchAlertsForInsights(insights: InsightModel[]): Promise<Map<number, AlertType[]>> {
    const alertsByInsightId = new Map<number, AlertType[]>()

    const insightsWithIds = insights.filter((i) => i.id)
    if (insightsWithIds.length === 0) {
        return alertsByInsightId
    }

    const alertPromises = insightsWithIds.map(async (insight) => {
        try {
            const response = await api.alerts.list(insight.id)
            return { insightId: insight.id, alerts: response.results }
        } catch (e) {
            posthog.captureException(e instanceof Error ? e : new Error(String(e)), {
                extra: { context: 'TerraformExporter', operation: 'fetchAlertsForInsights', insightId: insight.id },
            })
            return { insightId: insight.id, alerts: [] }
        }
    })

    const results = await Promise.all(alertPromises)
    for (const { insightId, alerts } of results) {
        if (alerts.length > 0) {
            alertsByInsightId.set(insightId, alerts)
        }
    }

    return alertsByInsightId
}

async function fetchHogFunctionsForAlerts(alerts: AlertType[]): Promise<Map<string, HogFunctionType[]>> {
    const hogFunctionsByAlertId = new Map<string, HogFunctionType[]>()

    if (alerts.length === 0) {
        return hogFunctionsByAlertId
    }

    const hogFunctionPromises = alerts.map(async (alert) => {
        try {
            const response = await api.hogFunctions.list({
                filter_groups: [buildAlertFilterConfig(alert.id)],
                types: ['internal_destination'],
                full: true,
            })
            return { alertId: alert.id, hogFunctions: response.results }
        } catch (e) {
            posthog.captureException(e instanceof Error ? e : new Error(String(e)), {
                extra: { context: 'TerraformExporter', operation: 'fetchHogFunctionsForAlerts', alertId: alert.id },
            })
            return { alertId: alert.id, hogFunctions: [] }
        }
    })

    const results = await Promise.all(hogFunctionPromises)
    for (const { alertId, hogFunctions } of results) {
        if (hogFunctions.length > 0) {
            hogFunctionsByAlertId.set(alertId, hogFunctions)
        }
    }

    return hogFunctionsByAlertId
}

async function exportInsight(insight: Partial<InsightModel>, checkStale: () => boolean): Promise<InsightExportResult> {
    const insights = insight.id ? [insight as InsightModel] : []
    const alertsByInsightId = await fetchAlertsForInsights(insights)

    if (checkStale()) {
        throw new Error('Fetch cancelled')
    }

    const alerts = Array.from(alertsByInsightId.values()).flat()
    const hogFunctionsByAlertId = await fetchHogFunctionsForAlerts(alerts)

    if (checkStale()) {
        throw new Error('Fetch cancelled')
    }

    try {
        return generateInsightHCL(insight, {
            alerts,
            hogFunctionsByAlertId,
        })
    } catch (e) {
        const resourceId = insight.id || insight.short_id || 'unknown'
        const resourceName = insight.name || 'unnamed insight'
        throw new Error(
            `Failed to generate HCL for insight "${resourceName}" (${resourceId}): ${e instanceof Error ? e.message : String(e)}`
        )
    }
}

async function exportDashboard(
    dashboard: DashboardType<QueryBasedInsightModel>,
    checkStale: () => boolean
): Promise<DashboardExportResult> {
    const insights: InsightModel[] = dashboard.tiles
        .filter((tile) => tile.insight)
        .map((tile) => tile.insight as InsightModel)

    const alertsByInsightId = await fetchAlertsForInsights(insights)

    if (checkStale()) {
        throw new Error('Fetch cancelled')
    }

    const allAlerts = Array.from(alertsByInsightId.values()).flat()
    const hogFunctionsByAlertId = await fetchHogFunctionsForAlerts(allAlerts)

    if (checkStale()) {
        throw new Error('Fetch cancelled')
    }

    try {
        return generateDashboardHCL(dashboard, {
            insights,
            alertsByInsightId,
            hogFunctionsByAlertId,
        })
    } catch (e) {
        const resourceId = dashboard.id || 'unknown'
        const resourceName = dashboard.name || 'unnamed dashboard'
        throw new Error(
            `Failed to generate HCL for dashboard "${resourceName}" (${resourceId}): ${e instanceof Error ? e.message : String(e)}`
        )
    }
}

export function useTerraformDownload(result: TerraformExportResult | null, baseName: string): () => void {
    return useCallback(() => {
        if (!result) {
            return
        }

        const filename = `${baseName}.tf`
        const blob = new Blob([result.hcl], { type: 'text/plain' })
        const url = URL.createObjectURL(blob)
        const a = document.createElement('a')
        a.href = url
        a.download = filename
        document.body.appendChild(a)
        a.click()
        document.body.removeChild(a)
        URL.revokeObjectURL(url)
    }, [result, baseName])
}

/**
 * Unified hook for exporting any resource type to Terraform.
 * Handles fetching related resources and generating HCL.
 */
export function useTerraformExport(resource: TerraformExportResource, isOpen: boolean): TerraformExportState {
    const [state, setState] = useState<TerraformExportState>({
        loading: true,
        error: null,
        result: null,
    })
    const isMountedRef = useRef(true)
    const fetchIdRef = useRef(0)

    useEffect(() => {
        isMountedRef.current = true
        return () => {
            isMountedRef.current = false
        }
    }, [])

    const fetchAndGenerate = useCallback(
        async (res: TerraformExportResource, checkStale: () => boolean): Promise<TerraformExportResult> => {
            if (res.type === 'dashboard') {
                return exportDashboard(res.data, checkStale)
            }
            return exportInsight(res.data, checkStale)
        },
        []
    )

    useEffect(() => {
        if (!isOpen) {
            return
        }

        const currentFetchId = ++fetchIdRef.current
        const isStale = (): boolean => !isMountedRef.current || fetchIdRef.current !== currentFetchId

        const fetchData = async (): Promise<void> => {
            setState({ loading: true, error: null, result: null })

            try {
                const result = await fetchAndGenerate(resource, isStale)
                if (!isStale()) {
                    setState({ loading: false, error: null, result })
                }
            } catch (e) {
                posthog.captureException(e instanceof Error ? e : new Error(String(e)), {
                    extra: { context: 'TerraformExporter', resourceType: resource.type, resourceId: resource.data.id },
                })
                if (!isStale()) {
                    setState({
                        loading: false,
                        error: e instanceof Error ? e.message : 'Failed to fetch data',
                        result: null,
                    })
                }
            }
        }

        void fetchData()
    }, [isOpen, resource, fetchAndGenerate])

    return state
}
