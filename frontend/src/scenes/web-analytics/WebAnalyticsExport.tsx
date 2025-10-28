import { useValues } from 'kea'

import { IconCopy } from '@posthog/icons'
import { LemonButton, LemonMenu } from '@posthog/lemon-ui'

import { copyTableToCsv, copyTableToExcel, copyTableToJson } from '~/queries/nodes/DataTable/clipboardUtils'
import { DataTableRow } from '~/queries/nodes/DataTable/dataTableLogic'
import {
    DataTableNode,
    NodeKind,
    QuerySchema,
    TrendsQueryResponse,
    WebStatsTableQueryResponse,
} from '~/queries/schema/schema-general'
import { isWebExternalClicksQuery, isWebGoalsQuery, isWebStatsTableQuery } from '~/queries/utils'
import { ExporterFormat, InsightLogicProps } from '~/types'

import { insightDataLogic } from '../insights/insightDataLogic'
import {
    CalendarHeatmapAdapter,
    TrendsAdapter,
    WebAnalyticsTableAdapter,
    WorldMapAdapter,
    exportTableData,
} from './webAnalyticsExportUtils'

interface WebAnalyticsExportProps {
    query: QuerySchema
    insightProps: InsightLogicProps
}

export function WebAnalyticsExport({ query, insightProps }: WebAnalyticsExportProps): JSX.Element | null {
    // For queries, use insightDataLogic - must be called before any early returns
    const builtInsightDataLogic = insightDataLogic(insightProps)
    const { insightDataRaw } = useValues(builtInsightDataLogic)

    if (!insightDataRaw) {
        return null
    }

    // Try to find an appropriate adapter for this query and response
    const adapters = [
        new CalendarHeatmapAdapter(insightDataRaw as TrendsQueryResponse, query),
        new WorldMapAdapter(insightDataRaw as TrendsQueryResponse, query),
        new WebAnalyticsTableAdapter(insightDataRaw as WebStatsTableQueryResponse, query),
        new TrendsAdapter(insightDataRaw as TrendsQueryResponse, query),
    ]
    const adapter = adapters.find((a) => a.canHandle())

    if (!adapter) {
        // Check if we need to handle non-web-analytics table queries
        if (query.kind === NodeKind.DataTableNode) {
            const tableResponse = insightDataRaw as WebStatsTableQueryResponse
            const columns = (tableResponse.columns as string[]) || []
            const dataTableQuery = query as DataTableNode
            const source = dataTableQuery.source
            const isWebAnalyticsTable =
                isWebStatsTableQuery(source) || isWebGoalsQuery(source) || isWebExternalClicksQuery(source)

            // If not a web analytics table, use fallback to clipboardUtils
            if (!isWebAnalyticsTable && tableResponse.results && tableResponse.results.length > 0 && columns.length) {
                const handleCopy = (format: ExporterFormat): void => {
                    const dataTableRows: DataTableRow[] = tableResponse.results.map((result) => ({
                        result: result as Record<string, any> | any[],
                    }))

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
                        <LemonButton
                            type="secondary"
                            icon={<IconCopy />}
                            size="small"
                            data-attr="web-analytics-copy-dropdown"
                        >
                            Copy
                        </LemonButton>
                    </LemonMenu>
                )
            }
        }

        return null
    }

    const handleCopy = (format: ExporterFormat): void => {
        const tableData = adapter.toTableData()
        exportTableData(tableData, format)
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
