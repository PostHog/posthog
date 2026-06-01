import '@testing-library/jest-dom'

// The renderer pulls in heavy transitive UI (notebook editor, session player). The registry-wiring
// test only needs identity, so stub the leaf component to keep the module graph light.
jest.mock('../NotebookArtifactAnswer', () => ({
    NotebookArtifactAnswer: () => null,
}))

import { lookupMcpToolRenderer, mcpToolRegistry } from '../../mcpToolRegistry'
import { CREATE_NOTEBOOK_TOOL_KEY, CreateNotebookAdapter } from './CreateNotebookAdapter'

describe('CreateNotebookAdapter registry wiring', () => {
    it('resolves the notebook adapter for the notebooks-create inner tool key', () => {
        const entry = lookupMcpToolRenderer(CREATE_NOTEBOOK_TOOL_KEY)

        expect(entry.key).toBe(CREATE_NOTEBOOK_TOOL_KEY)
        expect(entry.Renderer).toBe(CreateNotebookAdapter)
    })

    it('exposes the notebook adapter via direct registry lookup', () => {
        expect(mcpToolRegistry.lookup(CREATE_NOTEBOOK_TOOL_KEY)?.Renderer).toBe(CreateNotebookAdapter)
    })

    it('falls back to the generic renderer for an unknown inner tool key', () => {
        const entry = lookupMcpToolRenderer('some-unwired-tool')

        expect(entry.Renderer).not.toBe(CreateNotebookAdapter)
    })
})
