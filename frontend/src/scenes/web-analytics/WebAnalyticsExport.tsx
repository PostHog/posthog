import { useValues } from 'kea'

import { IconCopy } from '@posthog/icons'
import { LemonButton, LemonMenu } from '@posthog/lemon-ui'

import {
    copyTableToCsv,
    copyTableToExcel,
    copyTableToJson,
    copyWebTrendsToCsv,
    copyWebTrendsToExcel,
    copyWebTrendsToJson,
} from '~/queries/nodes/DataTable/clipboardUtils'
import { DataTableRow } from '~/queries/nodes/DataTable/dataTableLogic'
import {
    DataTableNode,
    InsightVizNode,
    NodeKind,
    QuerySchema,
    WebStatsTableQueryResponse,
    WebTrendsQueryResponse,
} from '~/queries/schema/schema-general'
import { isWebTrendsQuery } from '~/queries/utils'
import { ExporterFormat, InsightLogicProps } from '~/types'

import { insightDataLogic } from '../insights/insightDataLogic'

interface WebAnalyticsExportProps {
    query: QuerySchema
    insightProps: InsightLogicProps
}

export function WebAnalyticsExport({ query, insightProps }: WebAnalyticsExportProps): JSX.Element | null {
    const builtInsightDataLogic = insightDataLogic(insightProps)
    const { insightDataRaw } = useValues(builtInsightDataLogic)

    const isTableQuery = query.kind === NodeKind.DataTableNode
    const isInsightVizQuery =
        query.kind === NodeKind.InsightVizNode && isWebTrendsQuery((query as InsightVizNode).source)

    if (!isTableQuery && !isInsightVizQuery) {
        return null
    }

    if (!insightDataRaw) {
        return null
    }

    let hasData = false
    if (isTableQuery) {
        const tableResponse = insightDataRaw as WebStatsTableQueryResponse
        hasData = tableResponse.results && tableResponse.results.length > 0
    } else if (isInsightVizQuery) {
        const trendsResponse = insightDataRaw as WebTrendsQueryResponse
        hasData = trendsResponse.results && trendsResponse.results.length > 0
    }

    if (!hasData) {
        return null
    }

    const handleCopy = (format: ExporterFormat): void => {
        if (isTableQuery) {
            const tableResponse = insightDataRaw as WebStatsTableQueryResponse
            const columns = (tableResponse.columns as string[]) || []
            const dataTableRows: DataTableRow[] = tableResponse.results.map((result) => ({
                result: result as Record<string, any> | any[],
            }))

            if (!dataTableRows.length || !columns.length) {
                return
            }

            const dataTableQuery = query as DataTableNode

            switch (format) {
                case ExporterFormat.CSV:
                    copyTableToCsv(dataTableRows, columns, dataTableQuery, columns)
                    break
                case ExporterFormat.JSON:
                    copyTableToJson(dataTableRows, columns, dataTableQuery)
                    break
                case ExporterFormat.XLSX:
                    copyTableToExcel(dataTableRows, columns, dataTableQuery, columns)
                    break
            }
        } else if (isInsightVizQuery) {
            const trendsResponse = insightDataRaw as WebTrendsQueryResponse

            switch (format) {
                case ExporterFormat.CSV:
                    copyWebTrendsToCsv(trendsResponse)
                    break
                case ExporterFormat.JSON:
                    copyWebTrendsToJson(trendsResponse)
                    break
                case ExporterFormat.XLSX:
                    copyWebTrendsToExcel(trendsResponse)
                    break
            }
        }
    }

    return (
        <LemonMenu
            items={[
                {
                    label: 'CSV',
                    onClick: () => handleCopy(ExporterFormat.CSV),
                },
                {
                    label: 'JSON',
                    onClick: () => handleCopy(ExporterFormat.JSON),
                },
                {
                    label: 'Excel',
                    onClick: () => handleCopy(ExporterFormat.XLSX),
                },
            ]}
            placement="bottom-end"
        >
            <LemonButton type="secondary" icon={<IconCopy />} size="small" data-attr="web-analytics-copy-dropdown">
                Copy
            </LemonButton>
        </LemonMenu>
    )
}
