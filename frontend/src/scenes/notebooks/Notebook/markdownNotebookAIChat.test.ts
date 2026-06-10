import { ThreadMessage } from 'scenes/max/maxThreadLogic'

import { AssistantMessageType } from '~/queries/schema/schema-assistant-messages'

import { getInlineAICompletion, getNotebookAIChatThreadMessages } from './MarkdownNotebookAIChat'

const LONG_THINKING =
    'The user wants to add a pie chart to their notebook. I need to create an insight (pie chart) and then ' +
    'add it to the notebook. Let me first create a pie chart insight, then add it to the notebook.'

function humanMessage(content: string): ThreadMessage {
    return { type: AssistantMessageType.Human, content, status: 'completed' } as ThreadMessage
}

function assistantMessage(content: string, status: 'loading' | 'completed' = 'completed'): ThreadMessage {
    return { type: AssistantMessageType.Assistant, content, status } as ThreadMessage
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

describe('markdown notebook AI chat messages', () => {
    it('does not render a completed message that only carries thinking metadata', () => {
        const messages = getNotebookAIChatThreadMessages(
            [
                humanMessage('add a pie chart here'),
                assistantMessage("I'll create a pie chart insight first, then add it to the notebook."),
                notebookArtifactMessage(),
                thinkingOnlyMessage('completed'),
            ],
            false
        )

        expect(messages.map((message) => message.role)).toEqual(['human', 'assistant', 'assistant'])
        expect(messages.at(-1)?.content).toEqual('Updated the notebook.')
    })

    it('renders a truncated thinking status while a message is streaming', () => {
        const messages = getNotebookAIChatThreadMessages([humanMessage('hello'), thinkingOnlyMessage('loading')], true)

        expect(messages.at(-1)?.role).toEqual('thinking')
        expect((messages.at(-1)?.content ?? '').length).toBeLessThanOrEqual(160)
    })

    it('keeps a trailing thinking indicator while the thread is loading', () => {
        const messages = getNotebookAIChatThreadMessages([humanMessage('hello')], true)

        expect(messages.at(-1)).toMatchObject({ role: 'thinking', content: 'Thinking ...' })
    })

    it('reports inline completion after a notebook artifact even with a trailing thinking-only message', () => {
        const completion = getInlineAICompletion([
            humanMessage('add a pie chart here'),
            notebookArtifactMessage(),
            thinkingOnlyMessage('completed'),
        ])

        expect(completion).toEqual({ status: 'done', message: 'Updated the notebook.' })
    })
})
