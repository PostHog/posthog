import { useValues } from 'kea'

import { IconCopy } from '@posthog/icons'
import { LemonButton, LemonMenu } from '@posthog/lemon-ui'

import { copyTableToCsv, copyTableToExcel, copyTableToJson } from '~/queries/nodes/DataTable/clipboardUtils'
import { dataTableLogic } from '~/queries/nodes/DataTable/dataTableLogic'
import { insightVizDataNodeKey } from '~/queries/nodes/InsightViz/InsightViz'
import { DataTableNode, NodeKind, QuerySchema } from '~/queries/schema/schema-general'
import { ExporterFormat, InsightLogicProps } from '~/types'

interface WebAnalyticsExportProps {
    query: QuerySchema
    insightProps: InsightLogicProps
}

export function WebAnalyticsExport({ query, insightProps }: WebAnalyticsExportProps): JSX.Element | null {
    const vizKey = insightVizDataNodeKey(insightProps)

    // Construct the props for dataTableLogic
    const dataTableLogicProps = {
        vizKey,
        dataKey: vizKey,
        query:
            query.kind === NodeKind.DataTableNode
                ? query
                : ({
                      kind: NodeKind.DataTableNode,
                      source: { kind: NodeKind.HogQLQuery, query: '' },
                  } as DataTableNode),
    }

    // Always call useValues to comply with hooks rules
    const builtLogic = dataTableLogic(dataTableLogicProps)
    const { dataTableRows, columnsInResponse, queryWithDefaults } = useValues(builtLogic)

    // Check if logic is mounted and we have exportable data
    const isMounted = dataTableLogic.isMounted(dataTableLogicProps)
    const hasData = isMounted && dataTableRows && dataTableRows.length > 0

    if (!hasData) {
        return null
    }

    // Helper to create a DataTableNode for clipboard utils
    const createDataTableQuery = (): DataTableNode => {
        // Use the queryWithDefaults if available, otherwise construct from the passed query
        if (queryWithDefaults) {
            return queryWithDefaults
        }
        return dataTableLogicProps.query
    }

    const handleCopy = (format: ExporterFormat): void => {
        if (!dataTableRows || !columnsInResponse) {
            return
        }

        const dataTableQuery = createDataTableQuery()

        switch (format) {
            case ExporterFormat.CSV:
                copyTableToCsv(dataTableRows, columnsInResponse, dataTableQuery, columnsInResponse)
                break
            case ExporterFormat.JSON:
                copyTableToJson(dataTableRows, columnsInResponse, dataTableQuery)
                break
            case ExporterFormat.XLSX:
                copyTableToExcel(dataTableRows, columnsInResponse, dataTableQuery, columnsInResponse)
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
            <LemonButton type="secondary" icon={<IconCopy />} size="small" data-attr="web-analytics-copy-dropdown">
                Copy
            </LemonButton>
        </LemonMenu>
    )
}
