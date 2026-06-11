import { IconCopy } from '@posthog/icons'
import { LemonButton, LemonMenu } from '@posthog/lemon-ui'

import { QuerySchema } from '~/queries/schema/schema-general'
import { ExporterFormat, InsightLogicProps } from '~/types'

import { exportTableData } from './webAnalyticsExportUtils'
import { useWebTileExportAdapter } from './webTileHeaderHooks'

interface WebAnalyticsExportProps {
    query: QuerySchema
    insightProps: InsightLogicProps
}

export function WebAnalyticsExport({ query, insightProps }: WebAnalyticsExportProps): JSX.Element | null {
    const adapter = useWebTileExportAdapter(query, insightProps)

    if (!adapter) {
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
