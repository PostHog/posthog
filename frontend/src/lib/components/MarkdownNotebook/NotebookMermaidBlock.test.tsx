import '@testing-library/jest-dom'

import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'

import { NotebookBlockNode, NotebookCodeBlockNode } from './types'

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

// NotebookMermaidBlock lazy-loads MermaidDiagram; import it eagerly so Jest caches the chunk before
// the test runs, keeping the cold transform out of findByTestId's 1000ms window (flaky under CI load).
import 'lib/lemon-ui/LemonMarkdown/MermaidDiagram'

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

        render(
            <NotebookMermaidBlock
                node={codeNode('flowchart LR; A-->B', 'mermaid')}
                mode="view"
                setBlockRef={setBlockRef}
                updateNode={jest.fn()}
            />
        )

        const container = await screen.findByTestId('mermaid-rendered')
        expect(container.innerHTML).toContain('rendered')
        expect(renderMock).toHaveBeenCalledWith(expect.any(String), 'flowchart LR; A-->B')
        expect(setBlockRef).toHaveBeenCalledWith(expect.any(HTMLElement))
        expect(screen.queryByLabelText('Edit diagram')).not.toBeInTheDocument()
    })

    it('falls back to the plain source when the diagram fails to render', async () => {
        renderMock.mockRejectedValue(new Error('Parse error: bad syntax'))

        render(
            <NotebookMermaidBlock
                node={codeNode('not-a-real-diagram', 'mermaid')}
                mode="view"
                setBlockRef={jest.fn()}
                updateNode={jest.fn()}
            />
        )

        const errorContainer = await screen.findByTestId('mermaid-error')
        expect(errorContainer).toHaveTextContent('not-a-real-diagram')
    })

    it('edits a diagram without exposing the notebook markdown source', async () => {
        const node = codeNode('flowchart LR; A-->B', 'mermaid')
        const updateNode = jest.fn()
        renderMock.mockImplementation((_id: string, code: string) =>
            code.endsWith('-->')
                ? Promise.reject(new Error('Parse error: incomplete edge'))
                : Promise.resolve({ svg: '<svg data-testid="rendered"><g/></svg>' })
        )

        render(<NotebookMermaidBlock node={node} mode="edit" setBlockRef={jest.fn()} updateNode={updateNode} />)

        fireEvent.click(screen.getByLabelText('Edit diagram'))
        const definition = screen.getByLabelText('Mermaid definition')
        expect(definition).toHaveValue(node.text)

        fireEvent.change(definition, { target: { value: 'flowchart LR; A-->' } })
        expect(await screen.findByTestId('mermaid-error')).toHaveTextContent('incomplete edge')
        expect(definition).toHaveValue('flowchart LR; A-->')

        fireEvent.change(definition, { target: { value: 'flowchart LR; A-->C' } })
        await waitFor(() => expect(renderMock).toHaveBeenCalledWith(expect.any(String), 'flowchart LR; A-->C'))
        fireEvent.click(screen.getByText('Save diagram'))

        expect(updateNode).toHaveBeenCalledWith(node.id, expect.any(Function))
        const updater = updateNode.mock.calls[0][1] as (currentNode: NotebookBlockNode) => NotebookBlockNode | null
        expect(updater(node)).toEqual({ ...node, text: 'flowchart LR; A-->C' })
        await waitFor(() => expect(screen.queryByLabelText('Mermaid definition')).not.toBeInTheDocument())
    })
})
