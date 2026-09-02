import { parseMarkdownNotebook } from 'lib/components/MarkdownNotebook/markdown'
import { ThreadMessage } from 'scenes/max/maxThreadLogic'

import { AssistantMessageType } from '~/queries/schema/schema-assistant-messages'

import { getInlineAICompletion } from './MarkdownNotebookInlineAI'
import { getInlineNotebookAIUIContext } from './markdownNotebookRuntime'

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

    it('keeps cached binary output out of the notebook AI context', () => {
        const imageData = 'a'.repeat(120_000)
        const markdown = `<PythonV2 title="Chart" code="print('chart')" result={{"columns":[],"stdout":"done","media":[{"mime_type":"image/png","data":"${imageData}"}]}} />`

        const uiContext = getInlineNotebookAIUIContext({
            notebookShortId: 'test-notebook',
            notebookTitle: 'Test notebook',
            markdown,
            conversationId: 'test-conversation',
        })
        const contextMarkdown = uiContext?.notebooks?.[0].markdown_with_insertion_placeholder ?? ''

        expect(contextMarkdown).not.toContain(imageData)
        expect(contextMarkdown.length).toBeLessThan(markdown.length)
        expect(contextMarkdown).toContain(`code="print('chart')"`)
        expect(contextMarkdown).toContain('"stdout":"done"')
        expect(contextMarkdown).not.toContain('"media"')
        expect(markdown).toContain(imageData)
    })

    it('strips media even when a malformed prop makes the serializer prefer raw', () => {
        const imageData = 'a'.repeat(120_000)
        // A trailing unterminated quote makes the tag parse with an error, so it keeps `raw` and
        // `errors` alongside a fully parsed `result.media`.
        const markdown = `<PythonV2 code="print('chart')" result={{"columns":[],"stdout":"done","media":[{"mime_type":"image/png","data":"${imageData}"}]}} broken="unterminated />`

        // Guard the precondition: without errors + raw the serializer never hits the raw branch.
        const parsed = parseMarkdownNotebook(markdown)
        const componentNode = parsed.nodes.find((node) => node.type === 'component')
        expect(componentNode?.type).toBe('component')
        if (componentNode?.type === 'component') {
            expect(componentNode.errors?.length).toBeGreaterThan(0)
            expect(componentNode.raw).toContain(imageData)
            expect((componentNode.props.result as { media?: unknown[] }).media?.length).toBeGreaterThan(0)
        }

        const uiContext = getInlineNotebookAIUIContext({
            notebookShortId: 'test-notebook',
            notebookTitle: 'Test notebook',
            markdown,
            conversationId: 'test-conversation',
        })
        const contextMarkdown = uiContext?.notebooks?.[0].markdown_with_insertion_placeholder ?? ''

        expect(contextMarkdown).not.toContain(imageData)
        expect(contextMarkdown).not.toContain('"media"')
        expect(contextMarkdown).toContain(`code="print('chart')"`)
    })

    it('strips media from legacy Python execution props', () => {
        const imageData = 'a'.repeat(120_000)
        // Legacy cells nest media inside pythonExecution/duckExecution/hogqlExecution, not a
        // top-level result.
        const markdown = `<Python pythonExecution={{"status":"ok","stdout":"done","result":"42","media":[{"mimeType":"image/png","data":"${imageData}"}]}} />`

        // Guard the precondition: the media really lives under the execution prop, not `result`.
        const parsed = parseMarkdownNotebook(markdown)
        const componentNode = parsed.nodes.find((node) => node.type === 'component')
        expect(componentNode?.type).toBe('component')
        if (componentNode?.type === 'component') {
            expect((componentNode.props.pythonExecution as { media?: unknown[] }).media?.length).toBeGreaterThan(0)
        }

        const uiContext = getInlineNotebookAIUIContext({
            notebookShortId: 'test-notebook',
            notebookTitle: 'Test notebook',
            markdown,
            conversationId: 'test-conversation',
        })
        const contextMarkdown = uiContext?.notebooks?.[0].markdown_with_insertion_placeholder ?? ''

        expect(contextMarkdown).not.toContain(imageData)
        expect(contextMarkdown).not.toContain('"media"')
        expect(contextMarkdown).toContain('"stdout":"done"')
        expect(contextMarkdown).toContain('"result":"42"')
        expect(markdown).toContain(imageData)
    })
})
