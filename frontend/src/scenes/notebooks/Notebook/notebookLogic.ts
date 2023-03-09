import { actions, defaults, kea, key, path } from 'kea'
import { loaders } from 'kea-loaders'
import { NodeType } from 'scenes/notebooks/Nodes/types'

import type { notebookLogicType } from './notebookLogicType'

const START_CONTENT = `
<h2>Introducing Notebook!</h2>
<blockquote>This is experimental</blockquote>
<ph-query></ph-query>

<ph-insight shortId="OlmLXv6Q"></ph-insight>

<h3>An interesting recording I found</h3>

<p>This recording highlights perectly why...</p>
<br/>
<ph-recording sessionRecordingId="186c620122516e6-0ebf2e4cc8b8da-1f525634-16a7f0-186c62012262dfa"></ph-recording>
`

export const notebookLogic = kea<notebookLogicType>([
    path(['scenes', 'notebooks', 'Notebook', 'notebookLogic']),
    key(() => 'global'),
    actions({
        addNodeToNotebook: (type: NodeType, props: Record<string, any>) => ({ type, props }),
    }),
    defaults({
        content: START_CONTENT as string,
    }),
    loaders(({ values }) => ({
        content: {
            addNodeToNotebook: ({ type, props }) => {
                let attributes = ''

                if (type === NodeType.Recording) {
                    attributes = `sessionRecordingId="${props.sessionRecordingId}"`
                }

                return `
                ${values.content}
                <${type} ${attributes}></${type}>
                `
            },
        },
    })),
])
