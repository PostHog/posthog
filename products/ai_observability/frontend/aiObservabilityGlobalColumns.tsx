import { QueryContextColumn } from '~/queries/types'

import { AIObservabilityGlobalColumnCell } from './AIObservabilityGlobalColumnCell'

// Each entry names its own renderer, so the cell does not depend on the column name it is given.
function globalColumn(rendererKey: string): QueryContextColumn {
    return {
        render: function AIObservabilityGlobalColumn(props) {
            return <AIObservabilityGlobalColumnCell rendererKey={rendererKey} {...props} />
        },
    }
}

// The renderers that `renderColumn` applies to every DataTable in the app. A key here wins over the
// core renderer for that column name everywhere, so only namespaced keys belong: a `$ai_` property,
// or a name carrying the `__llm_` prefix. A plain name such as `person` would take the column over
// in the events table and the persons list too. Scenes opt into the rest through their own
// QueryContext, the way AIObservabilityTracesScene does.
// The cell loads the renderers on first use, so a table without these columns skips that module.
export const aiObservabilityGlobalColumnRenderers: Record<string, QueryContextColumn> = Object.fromEntries(
    [
        'properties.$ai_input[-1]',
        'properties.$ai_input',
        'properties.$ai_output_choices',
        'properties.$ai_trace_id',
        'properties.$ai_tools_called',
        '__llm_sentiment',
        '__llm_tools',
        '__llm_person',
    ].map((rendererKey) => [rendererKey, globalColumn(rendererKey)])
)
