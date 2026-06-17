import type { McpToolCallMessage } from '../../maxTypes'
import { lookupMcpToolRenderer, mcpToolRegistry } from '../../mcpToolRegistry'
import { CreateNotebookWidget, extractNotebook } from './CreateNotebookWidget'

function toolMessage(rawOutput: unknown, innerInput?: Record<string, unknown>): McpToolCallMessage {
    return {
        id: 'call-1',
        resolvedKey: 'notebooks-create',
        rawServerName: 'posthog',
        rawToolName: 'mcp__posthog__exec',
        rawInput: {},
        innerInput,
        rawOutput,
        content: [],
        status: 'completed',
    }
}

describe('CreateNotebookWidget', () => {
    it.each(['notebooks-create', 'notebooks-partial-update', 'notebooks-retrieve', 'notebook-edit'])(
        'resolves %s to the notebook widget',
        (key) => {
            expect(mcpToolRegistry.lookup(key)?.Renderer).toBe(CreateNotebookWidget)
            expect(lookupMcpToolRenderer(key).Renderer).toBe(CreateNotebookWidget)
        }
    )

    it('falls back to the generic renderer for an unknown inner tool key', () => {
        expect(lookupMcpToolRenderer('some-unwired-tool').Renderer).not.toBe(CreateNotebookWidget)
    })

    describe('extractNotebook', () => {
        it('reads short_id, title, and the _posthogUrl enrichment from the REST payload', () => {
            const notebook = extractNotebook(
                toolMessage({
                    id: 'b3d0f2aa-1111-2222-3333-444455556666',
                    short_id: 'aBcDe123',
                    title: 'Churn deep dive',
                    content: { type: 'doc', content: [] },
                    version: 1,
                    _posthogUrl: 'https://us.posthog.com/project/1/notebooks/aBcDe123',
                })
            )
            expect(notebook).toEqual({
                shortId: 'aBcDe123',
                title: 'Churn deep dive',
                url: 'https://us.posthog.com/project/1/notebooks/aBcDe123',
            })
        })

        it('falls back to the input title when the payload title is missing', () => {
            const notebook = extractNotebook(toolMessage({ short_id: 'aBcDe123' }, { title: 'From input' }))
            expect(notebook).toEqual({ shortId: 'aBcDe123', title: 'From input', url: undefined })
        })

        it('returns null for outputs without a short_id or that are not objects', () => {
            expect(extractNotebook(toolMessage({ blocks: [], title: 'Legacy artifact shape' }))).toBeNull()
            expect(extractNotebook(toolMessage('created notebook aBcDe123'))).toBeNull()
            expect(extractNotebook(toolMessage(undefined))).toBeNull()
        })
    })
})
