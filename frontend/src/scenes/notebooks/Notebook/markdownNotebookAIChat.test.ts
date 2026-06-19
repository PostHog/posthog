import { ThreadMessage } from 'scenes/max/maxThreadLogic'

import { AssistantMessageType } from '~/queries/schema/schema-assistant-messages'

import {
    NotebookAIChatMessage,
    getInlineAICompletion,
    getNotebookAIChatDisplayMessages,
    getNotebookAIChatThreadMessages,
} from './MarkdownNotebookAIChat'

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

        expect(completion).toEqual({
            status: 'done',
            kind: 'artifact',
            hasArtifact: true,
            message: 'Updated the notebook.',
        })
    })

    describe('getNotebookAIChatDisplayMessages', () => {
        const localAnswer: NotebookAIChatMessage = { role: 'assistant', id: 'a1', content: 'A local answer' }

        it('prefers the local thread when it already shows the cached answer', () => {
            expect(getNotebookAIChatDisplayMessages([localAnswer], localAnswer.content)).toEqual([localAnswer])
        })

        it('renders the synced lastAnswer when the local thread is empty (collaborator view)', () => {
            expect(getNotebookAIChatDisplayMessages([], 'Streaming in from another client')).toEqual([
                {
                    role: 'assistant',
                    id: 'notebook-ai-chat-cached-answer',
                    content: 'Streaming in from another client',
                },
            ])
        })

        it('falls back to the thinking placeholder when nothing is available', () => {
            expect(getNotebookAIChatDisplayMessages([], null)).toEqual([
                { role: 'thinking', id: 'notebook-ai-chat-loading', content: 'Thinking ...' },
            ])
        })

        it('appends an answer that arrived via props while the local thread is idle', () => {
            // Someone replied from another window: their answer synced into lastAnswer.
            expect(getNotebookAIChatDisplayMessages([localAnswer], 'A newer remote answer', false)).toEqual([
                localAnswer,
                { role: 'assistant', id: 'notebook-ai-chat-remote-answer', content: 'A newer remote answer' },
            ])
        })

        it('does not append the cached answer while the local thread is streaming', () => {
            expect(getNotebookAIChatDisplayMessages([localAnswer], 'An older cached answer', true)).toEqual([
                localAnswer,
            ])
        })

        it('does not duplicate the answer this thread already shows', () => {
            expect(getNotebookAIChatDisplayMessages([localAnswer], localAnswer.content, false)).toEqual([localAnswer])
        })
    })
})
