import { ExportedInsight } from '~/exporter/ExportedInsight/ExportedInsight'

import { ExportedData } from '../types'

export default function ExporterInsightScene({
    insight,
    themes,
    exportOptions,
}: {
    insight: NonNullable<ExportedData['insight']>
    themes: NonNullable<ExportedData['themes']>
    exportOptions: Omit<
        ExportedData,
        | 'type'
        | 'dashboard'
        | 'insight'
        | 'recording'
        | 'notebook'
        | 'insights'
        | 'inline_query_results'
        | 'themes'
        | 'accessToken'
        | 'exportToken'
    >
}): JSX.Element {
    return <ExportedInsight insight={insight} themes={themes} exportOptions={exportOptions} />
}
