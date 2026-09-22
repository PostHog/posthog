import '@testing-library/jest-dom'

import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'

import { isMermaidCodeBlock } from './documentModel'
import { NotebookBlockNode, NotebookCodeBlockNode, NotebookMode } from './types'

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

import { NotebookMermaidBlock } from './NotebookMermaidBlock'

function codeNode(text: string, language: string | undefined): NotebookCodeBlockNode {
    return { id: 'block-1', type: 'code', language, text }
}

function renderBlock(
    node: NotebookCodeBlockNode,
    mode: NotebookMode,
    overrides: Partial<Parameters<typeof NotebookMermaidBlock>[0]> = {}
): ReturnType<typeof render> {
    return render(
        <NotebookMermaidBlock
            node={node}
            mode={mode}
            setBlockRef={jest.fn()}
            updateNode={jest.fn()}
            deleteNode={jest.fn()}
            deleteSelectedNotebookBlocks={jest.fn(() => false)}
            insertParagraphAfterNode={jest.fn()}
            moveFocusToAdjacentNode={jest.fn(() => false)}
            {...overrides}
        />
    )
}

describe('NotebookMermaidBlock', () => {
    afterEach(() => {
        cleanup()
        jest.clearAllMocks()
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

        renderBlock(codeNode('flowchart LR; A-->B', 'mermaid'), 'view', { setBlockRef })

        const container = await screen.findByTestId('mermaid-rendered')
        expect(container.innerHTML).toContain('rendered')
        expect(renderMock).toHaveBeenCalledWith(expect.any(String), 'flowchart LR; A-->B')
        expect(setBlockRef).toHaveBeenCalledWith(expect.any(HTMLElement))
        expect(screen.queryByLabelText('Edit diagram')).not.toBeInTheDocument()
    })

    it('falls back to the plain source when the diagram fails to render', async () => {
        renderMock.mockRejectedValue(new Error('Parse error: bad syntax'))

        renderBlock(codeNode('not-a-real-diagram', 'mermaid'), 'view')

        const errorContainer = await screen.findByTestId('mermaid-error')
        expect(errorContainer).toHaveTextContent('not-a-real-diagram')
    })

    it('edits a diagram without exposing the notebook markdown source', async () => {
        const node = codeNode('flowchart LR; A-->B', 'mermaid')
        const updateNode = jest.fn()
        const onInteractionStateChange = jest.fn()
        renderMock.mockImplementation((_id: string, code: string) =>
            code.endsWith('-->')
                ? Promise.reject(new Error('Parse error: incomplete edge'))
                : Promise.resolve({ svg: '<svg data-testid="rendered"><g/></svg>' })
        )

        const { unmount } = renderBlock(node, 'edit', { updateNode, onInteractionStateChange })

        fireEvent.click(screen.getByLabelText('Edit diagram'))
        expect(onInteractionStateChange).toHaveBeenLastCalledWith(true)
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
        await waitFor(() => expect(onInteractionStateChange).toHaveBeenLastCalledWith(false))
        expect(updateNode.mock.invocationCallOrder[0]).toBeLessThan(
            onInteractionStateChange.mock.invocationCallOrder[
                onInteractionStateChange.mock.invocationCallOrder.length - 1
            ]
        )

        fireEvent.click(screen.getByLabelText('Edit diagram'))
        expect(onInteractionStateChange).toHaveBeenLastCalledWith(true)
        unmount()
        expect(onInteractionStateChange).toHaveBeenLastCalledWith(false)
    })

    it('debounces the live preview so rapid edits do not each start a render', async () => {
        renderMock.mockResolvedValue({ svg: '<svg data-testid="rendered"><g/></svg>' })

        renderBlock(codeNode('flowchart LR; A-->B', 'mermaid'), 'edit')

        fireEvent.click(screen.getByLabelText('Edit diagram'))
        const definition = screen.getByLabelText('Mermaid definition')

        fireEvent.change(definition, { target: { value: 'flowchart LR; A-->C' } })
        fireEvent.change(definition, { target: { value: 'flowchart LR; A-->CD' } })
        fireEvent.change(definition, { target: { value: 'flowchart LR; A-->CDE' } })

        await waitFor(() => expect(renderMock).toHaveBeenCalledWith(expect.any(String), 'flowchart LR; A-->CDE'))
        expect(renderMock).not.toHaveBeenCalledWith(expect.any(String), 'flowchart LR; A-->C')
        expect(renderMock).not.toHaveBeenCalledWith(expect.any(String), 'flowchart LR; A-->CD')
    })

    it.each([
        [false, 1],
        [true, 0],
    ])(
        'deletes the focused diagram block on Backspace when a multi-block selection handled it is %p',
        (multiBlockHandled, expectedDeleteNodeCalls) => {
            const deleteNode = jest.fn()
            const deleteSelectedNotebookBlocks = jest.fn(() => multiBlockHandled)
            const { container } = renderBlock(codeNode('flowchart LR; A-->B', 'mermaid'), 'edit', {
                deleteNode,
                deleteSelectedNotebookBlocks,
            })

            const block = container.querySelector('.MarkdownNotebook__mermaid-block') as HTMLElement
            expect(block).toHaveAttribute('tabindex', '0')
            block.focus()
            fireEvent.keyDown(block, { key: 'Backspace' })

            expect(deleteSelectedNotebookBlocks).toHaveBeenCalledTimes(1)
            expect(deleteNode).toHaveBeenCalledTimes(expectedDeleteNodeCalls)
        }
    )

    it('moves focus from the diagram and inserts a paragraph with the keyboard', () => {
        renderMock.mockResolvedValue({ svg: '<svg data-testid="rendered"><g/></svg>' })
        const moveFocusToAdjacentNode = jest.fn(() => true)
        const insertParagraphAfterNode = jest.fn()
        const { container } = renderBlock(codeNode('flowchart LR; A-->B', 'mermaid'), 'edit', {
            insertParagraphAfterNode,
            moveFocusToAdjacentNode,
        })
        const block = container.querySelector('.MarkdownNotebook__mermaid-block') as HTMLElement

        fireEvent.keyDown(block, { key: 'ArrowDown' })
        expect(moveFocusToAdjacentNode).toHaveBeenCalledWith('block-1', 'next', 0)

        fireEvent.keyDown(block, { key: 'Enter' })
        expect(insertParagraphAfterNode).toHaveBeenCalledTimes(1)
    })
})
