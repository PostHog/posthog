import { cleanup, render, screen } from '@testing-library/react'

import { initKeaTests } from '~/test/init'

import { accountDotMatrixTileLogic } from './accountDotMatrixTileLogic'
import { DotMatrixQueryEditor } from './DotMatrixQueryEditor'

jest.mock('~/queries/query', () => ({ performQuery: jest.fn() }))

let mockEditorImports = 0
jest.mock('lib/monaco/CodeEditor', () => {
    mockEditorImports += 1
    if (mockEditorImports === 1) {
        throw new TypeError('Failed to fetch dynamically imported module: CodeEditor.js')
    }
    return { CodeEditor: () => <div data-attr="matrix-code-editor" /> }
})

describe('DotMatrixQueryEditor', () => {
    beforeEach(() => {
        initKeaTests()
    })
    afterEach(cleanup)

    it('recovers when the editor chunk fails to download once', async () => {
        const logic = accountDotMatrixTileLogic({
            instanceId: 'chunk',
            accountId: 'account-1',
            initialConfig: { source: null },
        })
        logic.mount()
        render(<DotMatrixQueryEditor logic={logic} />)

        expect(await screen.findByTestId('matrix-code-editor', {}, { timeout: 3000 })).toBeTruthy()
        expect(mockEditorImports).toBe(2)
        logic.unmount()
    })
})
