import { SharingConfigurationSettings } from '@posthog/query-frontend/schema/schema-general'

import { ExportedInsight } from '~/exporter/ExportedInsight/ExportedInsight'

import { ExportedData } from '../types'

export default function ExporterInsightScene({
    insight,
    themes,
    exportOptions,
}: {
    insight: NonNullable<ExportedData['insight']>
    themes: NonNullable<ExportedData['themes']>
    exportOptions: SharingConfigurationSettings
}): JSX.Element {
    return <ExportedInsight insight={insight} themes={themes} exportOptions={exportOptions} />
}
