import {
    lookupSandboxToolRenderer,
    sandboxToolRegistry,
} from 'products/posthog_ai/frontend/sandbox/sandboxToolRegistry'

import type { SandboxToolCallMessage } from '../../maxTypes'
import { extractNotebook } from './CreateNotebookWidget'

function toolMessage(rawOutput: unknown, innerInput?: Record<string, unknown>): SandboxToolCallMessage {
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
            expect(sandboxToolRegistry.lookup(key)?.displayName).toBe('Notebook')
            expect(lookupSandboxToolRenderer(key).displayName).toBe('Notebook')
        }
    )

    it('falls back to the generic renderer for an unknown inner tool key', () => {
        expect(lookupSandboxToolRenderer('some-unwired-tool').displayName).not.toBe('Notebook')
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
