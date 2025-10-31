import { IconWarning } from '@posthog/icons'
import { useValues } from 'kea'
import { useEffect, useState } from 'react'
import { api } from 'lib/api'
import { LemonBanner } from 'lib/lemon-ui/LemonBanner'
import { teamLogic } from 'scenes/teamLogic'
import { DataWarehouseSyncStatus } from '~/types'
import { Node } from '~/queries/schema'

interface DataWarehouseSyncNoticeProps {
    query: Node | null | undefined
}

function extractDataWarehouseTables(query: any): string[] {
    if (!query || typeof query !== 'object') {
        return []
    }

    const tableNames: string[] = []

    // Handle DataVisualizationNode
    if (query.kind === 'DataVisualizationNode' && query.source) {
        tableNames.push(...extractDataWarehouseTables(query.source))
    }

    // Handle HogQLQuery - table names would need to be parsed from the query string
    // For now, we don't extract from HogQLQuery on the frontend
    // The backend will handle this when checking sync status

    // Handle queries with series (TrendsQuery, FunnelsQuery, etc.)
    if (query.series && Array.isArray(query.series)) {
        for (const node of query.series) {
            if (node && typeof node === 'object' && node.kind === 'DataWarehouseNode' && node.table_name) {
                tableNames.push(node.table_name)
            }
        }
    }

    return tableNames
}

export function DataWarehouseSyncNotice({ query }: DataWarehouseSyncNoticeProps): JSX.Element | null {
    const { currentTeamId } = useValues(teamLogic)
    const [syncStatus, setSyncStatus] = useState<DataWarehouseSyncStatus[] | null>(null)
    const [loading, setLoading] = useState(false)

    useEffect(() => {
        const tableNames = extractDataWarehouseTables(query)
        if (tableNames.length === 0) {
            setSyncStatus(null)
            return
        }

        setLoading(true)
        api.dataWarehouseTables
            .syncStatus(tableNames)
            .then((status) => {
                setSyncStatus(status)
            })
            .catch(() => {
                setSyncStatus(null)
            })
            .finally(() => {
                setLoading(false)
            })
    }, [query, currentTeamId])

    if (loading || !syncStatus || syncStatus.length === 0) {
        return null
    }

    const failedSyncs = syncStatus.filter((s) => s.status === 'failed')
    const disabledSyncs = syncStatus.filter((s) => s.status === 'disabled')
    const pausedSyncs = syncStatus.filter((s) => s.status === 'paused')

    // Prioritize showing failed syncs first
    const primaryIssues = failedSyncs.length > 0 ? failedSyncs : disabledSyncs.length > 0 ? disabledSyncs : pausedSyncs

    if (primaryIssues.length === 0) {
        return null
    }

    const type = failedSyncs.length > 0 ? 'error' : 'warning'
    const primaryIssue = primaryIssues[0]

    // Build the message
    let message = primaryIssue.message
    if (primaryIssues.length > 1) {
        message = `${message} (and ${primaryIssues.length - 1} other table${primaryIssues.length > 2 ? 's' : ''})`
    }

    return (
        <LemonBanner type={type} className="mb-2" icon={<IconWarning />}>
            <div>
                <strong>Data may be out of date</strong>
                <div className="text-sm mt-1">{message}</div>
                {primaryIssue.error && (
                    <div className="text-xs mt-1 text-muted">
                        <strong>Error:</strong> {primaryIssue.error}
                    </div>
                )}
            </div>
        </LemonBanner>
    )
}
