import { Notebook } from 'scenes/notebooks/Notebook/Notebook'

import { ExportedData } from '../types'

export default function ExporterNotebookScene({
    notebook,
    insights,
    inline_query_results: inlineQueryResults,
}: Pick<ExportedData, 'notebook' | 'insights' | 'inline_query_results'>): JSX.Element {
    return (
        <Notebook
            shortId={notebook!.short_id}
            editable={false}
            cachedNotebook={notebook}
            cachedInsightsByShortId={insights}
            cachedInlineQueryResultsByNodeId={inlineQueryResults}
        />
    )
}
