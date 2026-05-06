import { ExportedInsight } from '~/exporter/ExportedInsight/ExportedInsight'
import { SharingConfigurationSettings } from '~/queries/schema/schema-general'

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
