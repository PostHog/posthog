import '@testing-library/jest-dom'

import { cleanup, render, screen } from '@testing-library/react'

import { NotebookCodeBlockNode } from './types'

jest.mock('kea', () => ({
    useValues: () => ({ isDarkModeOn: false }),
}))

jest.mock('~/layout/navigation-3000/themeLogic', () => ({
    themeLogic: { values: {} },
}))

const renderMock = jest.fn()

jest.mock('mermaid', () => ({
    __esModule: true,
    default: {
        initialize: jest.fn(),
        render: (...args: unknown[]) => renderMock(...args),
    },
}))

import { isMermaidCodeBlock, NotebookMermaidBlock } from './NotebookMermaidBlock'

function codeNode(text: string, language: string | undefined): NotebookCodeBlockNode {
    return { id: 'block-1', type: 'code', language, text }
}

describe('NotebookMermaidBlock', () => {
    afterEach(() => {
        cleanup()
        renderMock.mockReset()
    })

    it.each([
        ['mermaid', true],
        ['Mermaid', true],
        ['MERMAID', true],
        ['python', false],
        ['', false],
        [undefined, false],
    ])('isMermaidCodeBlock treats language %p as %p', (language, expected) => {
        expect(isMermaidCodeBlock(codeNode('flowchart LR; A-->B', language as string | undefined))).toBe(expected)
    })

    it('renders the diagram from the block source and registers a block ref', async () => {
        renderMock.mockResolvedValue({ svg: '<svg data-testid="rendered"><g/></svg>' })
        const setBlockRef = jest.fn()

        render(<NotebookMermaidBlock node={codeNode('flowchart LR; A-->B', 'mermaid')} setBlockRef={setBlockRef} />)

        const container = await screen.findByTestId('mermaid-rendered')
        expect(container.innerHTML).toContain('rendered')
        expect(renderMock).toHaveBeenCalledWith(expect.any(String), 'flowchart LR; A-->B')
        expect(setBlockRef).toHaveBeenCalledWith(expect.any(HTMLElement))
    })

    it('falls back to the plain source when the diagram fails to render', async () => {
        renderMock.mockRejectedValue(new Error('Parse error: bad syntax'))

        render(<NotebookMermaidBlock node={codeNode('not-a-real-diagram', 'mermaid')} setBlockRef={jest.fn()} />)

        const errorContainer = await screen.findByTestId('mermaid-error')
        expect(errorContainer).toHaveTextContent('not-a-real-diagram')
    })
})
