import { ThreadMessage } from 'scenes/max/maxThreadLogic'

import { AssistantMessageType } from '~/queries/schema/schema-assistant-messages'

import { getInlineAICompletion } from './MarkdownNotebookInlineAI'

const LONG_THINKING =
    'The user wants to add a pie chart to their notebook. I need to create an insight (pie chart) and then ' +
    'add it to the notebook. Let me first create a pie chart insight, then add it to the notebook.'

function humanMessage(content: string): ThreadMessage {
    return { type: AssistantMessageType.Human, content, status: 'completed' } as ThreadMessage
}

function thinkingOnlyMessage(status: 'loading' | 'completed'): ThreadMessage {
    return {
        type: AssistantMessageType.Assistant,
        content: '',
        status,
        meta: { thinking: [{ type: 'thinking', thinking: LONG_THINKING }] },
    } as unknown as ThreadMessage
}

function notebookArtifactMessage(): ThreadMessage {
    return {
        type: AssistantMessageType.Artifact,
        status: 'completed',
        artifact_id: 'artifact-1',
        content: { content_type: 'notebook', blocks: [] },
    } as unknown as ThreadMessage
}

describe('markdown notebook inline AI completion', () => {
    it('reports inline completion after a notebook artifact even with a trailing thinking-only message', () => {
        const completion = getInlineAICompletion([
            humanMessage('add a pie chart here'),
            notebookArtifactMessage(),
            thinkingOnlyMessage('completed'),
        ])

        expect(completion).toEqual({
            status: 'done',
            kind: 'artifact',
            hasArtifact: true,
            message: 'Updated the notebook.',
        })
    })
})
