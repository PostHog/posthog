import { Notebook } from 'scenes/notebooks/Notebook/Notebook'

import { ExportedData } from '../types'

export default function ExporterNotebookScene({
    notebook,
    insights,
    inline_query_results: inlineQueryResults,
}: {
    notebook: NonNullable<ExportedData['notebook']>
    insights: ExportedData['insights']
    inline_query_results: ExportedData['inline_query_results']
}): JSX.Element {
    return (
        <Notebook
            shortId={notebook.short_id}
            editable={false}
            cachedNotebook={notebook}
            cachedInsightsByShortId={insights}
            cachedInlineQueryResultsByNodeId={inlineQueryResults}
        />
    )
}
