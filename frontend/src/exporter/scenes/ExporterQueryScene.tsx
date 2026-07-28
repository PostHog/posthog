import '../ExportedInsight/ExportedInsight.scss'

import { useMountedLogic } from 'kea'

import { dataThemeLogic } from 'scenes/dataThemeLogic'

import { Query } from '~/queries/Query/Query'

import { ExportedData } from '../types'

/**
 * Renders an ad-hoc query export (`export_context.source`, no saved insight) from the
 * pre-computed result the sharing view inlined — never POSTs to the query API, which the
 * asset token can't authenticate. Reuses the ExportedInsight classes so the image
 * exporter's wait selector and content measurement work unchanged.
 */
export default function ExporterQueryScene({
    query,
    queryResults,
    themes,
}: {
    query: NonNullable<ExportedData['query']>
    queryResults: ExportedData['query_results']
    themes: NonNullable<ExportedData['themes']>
}): JSX.Element {
    useMountedLogic(dataThemeLogic({ themes }))

    return (
        <div className="ExportedInsight">
            <div className="ExportedInsight__content">
                <Query query={query} cachedResults={queryResults} embedded readOnly inSharedMode />
            </div>
        </div>
    )
}
