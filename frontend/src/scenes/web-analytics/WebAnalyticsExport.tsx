import { useValues } from 'kea'

import { IconCopy } from '@posthog/icons'
import { LemonButton, LemonMenu } from '@posthog/lemon-ui'

import { FEATURE_FLAGS } from 'lib/constants'
import { featureFlagsLogic } from 'scenes/feature-flags/featureFlagsLogic'

import { QuerySchema, TrendsQueryResponse, WebStatsTableQueryResponse } from '~/queries/schema/schema-general'
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
    const builtInsightDataLogic = insightDataLogic(insightProps)
    const { insightDataRaw } = useValues(builtInsightDataLogic)
    const { featureFlags } = useValues(featureFlagsLogic)

    if (!featureFlags[FEATURE_FLAGS.COPY_WEB_ANALYTICS_DATA]) {
        return null
    }

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
