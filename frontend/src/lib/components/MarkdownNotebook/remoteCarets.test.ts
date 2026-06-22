import { render, waitFor } from '@testing-library/react'
import { createElement } from 'react'

import { getListItemRefKey } from './listModel'
import { parseMarkdownNotebook } from './markdown'
import { reconcileNotebookDocuments } from './reconcile'
import {
    getFocusedBlockCaretPosition,
    mapRemoteCaretPositionThroughDocumentChange,
    RemoteCaretOverlay,
    resolveRemoteCaretLayout,
} from './remoteCarets'
import { NotebookBlockNode, NotebookDocument } from './types'

describe('remoteCarets', () => {
    const originalResizeObserver = global.ResizeObserver

    class ResizeObserverMock {
        observe(): void {}
        disconnect(): void {}
    }

    beforeEach(() => {
        ;(global as typeof globalThis & { ResizeObserver: typeof ResizeObserver | undefined }).ResizeObserver =
            ResizeObserverMock as unknown as typeof ResizeObserver
    })

    afterEach(() => {
        ;(global as typeof globalThis & { ResizeObserver: typeof ResizeObserver | undefined }).ResizeObserver =
            originalResizeObserver
    })

    const paragraph = (id: string, text: string): NotebookBlockNode => ({
        id,
        type: 'paragraph',
        children: [{ type: 'text', text }],
    })

    const list = (id: string, itemTexts: string[]): NotebookBlockNode => ({
        id,
        type: 'list',
        ordered: false,
        items: itemTexts.map((text) => ({ depth: 0, children: [{ type: 'text', text }] })),
    })

    function makeElement(text: string, rect: { top: number; left: number }): HTMLElement {
        const element = document.createElement('div')
        element.textContent = text
        element.getBoundingClientRect = () =>
            ({
                top: rect.top,
                left: rect.left,
                width: 100,
                height: 20,
                bottom: rect.top + 20,
                right: rect.left + 100,
            }) as DOMRect
        return element
    }

    const container = makeElement('', { top: 0, left: 0 })

    it('returns null when the node index is out of range', () => {
        const nodes = [paragraph('p1', 'hello')]
        expect(resolveRemoteCaretLayout({ nodeIndex: 5, offset: 0 }, nodes, {}, {}, container)).toBeNull()
    })

    it('returns null when the block element is not mounted', () => {
        const nodes = [paragraph('p1', 'hello')]
        expect(resolveRemoteCaretLayout({ nodeIndex: 0, offset: 0 }, nodes, { p1: null }, {}, container)).toBeNull()
    })

    it('positions relative to the container using the block element rect', () => {
        const nodes = [paragraph('p1', 'hello')]
        const element = makeElement('hello', { top: 130, left: 40 })
        // jsdom ranges have no layout, so the offset path falls back to the element rect
        const layout = resolveRemoteCaretLayout({ nodeIndex: 0, offset: 3 }, nodes, { p1: element }, {}, container)
        expect(layout).toMatchObject({ top: 130, left: 40 })
        expect(layout?.height).toBeGreaterThan(0)
    })

    it('clamps offsets beyond the text length instead of dropping the caret', () => {
        const nodes = [paragraph('p1', 'hi')]
        const element = makeElement('hi', { top: 10, left: 10 })
        expect(
            resolveRemoteCaretLayout({ nodeIndex: 0, offset: 999 }, nodes, { p1: element }, {}, container)
        ).not.toBeNull()
    })

    it('resolves list carets through the focused item element', () => {
        const nodes = [list('l1', ['one', 'two'])]
        const itemElement = makeElement('two', { top: 60, left: 24 })
        const layout = resolveRemoteCaretLayout(
            { nodeIndex: 0, offset: 1, listItemIndex: 1 },
            nodes,
            {},
            { [getListItemRefKey('l1', 1)]: itemElement },
            container
        )
        expect(layout).toMatchObject({ top: 60, left: 24 })
    })

    it('clamps the list item index to the last item', () => {
        const nodes = [list('l1', ['one'])]
        const itemElement = makeElement('one', { top: 30, left: 24 })
        const layout = resolveRemoteCaretLayout(
            { nodeIndex: 0, offset: 0, listItemIndex: 7 },
            nodes,
            {},
            { [getListItemRefKey('l1', 0)]: itemElement },
            container
        )
        expect(layout).toMatchObject({ top: 30, left: 24 })
    })

    it('resolves offset-less positions to a block outline with the element size', () => {
        const nodes = [paragraph('p1', 'hello')]
        const element = makeElement('hello', { top: 200, left: 16 })
        const layout = resolveRemoteCaretLayout({ nodeIndex: 0 }, nodes, { p1: element }, {}, container)
        expect(layout).toMatchObject({ top: 200, left: 16, width: 100, height: 20 })
    })

    it('resolves component positions to a block outline even when an offset sneaks in', () => {
        const nodes: NotebookBlockNode[] = [{ id: 'c1', type: 'component', tagName: 'Query', props: {} }]
        const element = makeElement('rendered query text', { top: 300, left: 16 })
        const layout = resolveRemoteCaretLayout({ nodeIndex: 0, offset: 4 }, nodes, { c1: element }, {}, container)
        expect(layout).toMatchObject({ top: 300, left: 16, width: 100, height: 20 })
    })

    it('renders AI thinking dots after the remote caret label', async () => {
        const nodes = [paragraph('p1', 'hello')]
        const element = makeElement('hello', { top: 20, left: 12 })
        const containerElement = makeElement('', { top: 0, left: 0 })
        const { container: renderedContainer } = render(
            createElement(RemoteCaretOverlay, {
                carets: [
                    {
                        clientId: 'notebook-agent:ai',
                        userName: 'AI',
                        color: 'green',
                        position: { nodeIndex: 0 },
                        isAI: true,
                        isAIThinking: true,
                    },
                ],
                nodes,
                blockRefs: { current: { p1: element } },
                listItemRefs: { current: {} },
                containerRef: { current: containerElement },
            })
        )

        await waitFor(() =>
            expect(renderedContainer.querySelectorAll('.MarkdownNotebook__remote-caret-ai-dots span')).toHaveLength(3)
        )
        expect(renderedContainer.querySelector('.MarkdownNotebook__remote-caret-flag')?.textContent).toEqual('AI...')
    })

    describe('mapRemoteCaretPositionThroughDocumentChange', () => {
        function evolve(markdown: string, nextMarkdown: string): [NotebookDocument, NotebookDocument] {
            const previousDocument = parseMarkdownNotebook(markdown)
            const nextDocument = reconcileNotebookDocuments(
                previousDocument,
                parseMarkdownNotebook(nextMarkdown)
            ).document
            return [previousDocument, nextDocument]
        }

        it('moves the caret right when text is inserted before it', () => {
            const [previousDocument, nextDocument] = evolve('# Title\n\nHello', '# Title\n\nWell, Hello')
            expect(
                mapRemoteCaretPositionThroughDocumentChange({ nodeIndex: 1, offset: 5 }, previousDocument, nextDocument)
            ).toEqual({ nodeIndex: 1, offset: 11, listItemIndex: undefined })
        })

        it('keeps the caret in place when text is inserted after it', () => {
            const [previousDocument, nextDocument] = evolve('# Title\n\nHello', '# Title\n\nHello world')
            const position = { nodeIndex: 1, offset: 0 }
            expect(mapRemoteCaretPositionThroughDocumentChange(position, previousDocument, nextDocument)).toBe(position)
        })

        it('updates the node index when a block is inserted above', () => {
            const [previousDocument, nextDocument] = evolve('# Title\n\nHello', '# Title\n\nNew paragraph\n\nHello')
            expect(
                mapRemoteCaretPositionThroughDocumentChange({ nodeIndex: 1, offset: 3 }, previousDocument, nextDocument)
            ).toEqual({ nodeIndex: 2, offset: 3, listItemIndex: undefined })
        })

        it('follows a list item by id when items are inserted above it', () => {
            const [previousDocument, nextDocument] = evolve('- one\n- two', '- zero\n- one\n- two')
            expect(
                mapRemoteCaretPositionThroughDocumentChange(
                    { nodeIndex: 0, offset: 3, listItemIndex: 1 },
                    previousDocument,
                    nextDocument
                )
            ).toEqual({ nodeIndex: 0, offset: 3, listItemIndex: 2 })
        })
    })

    describe('getFocusedBlockCaretPosition', () => {
        function makeBlocks(): {
            root: HTMLElement
            componentElement: HTMLElement
            innerButton: HTMLElement
            nodes: NotebookBlockNode[]
            blockRefs: Record<string, HTMLElement | null>
        } {
            const root = document.createElement('div')
            const paragraphElement = document.createElement('div')
            const componentElement = document.createElement('div')
            const innerButton = document.createElement('button')
            componentElement.appendChild(innerButton)
            root.appendChild(paragraphElement)
            root.appendChild(componentElement)
            const nodes: NotebookBlockNode[] = [
                paragraph('p1', 'hello'),
                { id: 'c1', type: 'component', tagName: 'Query', props: {} },
            ]
            return {
                root,
                componentElement,
                innerButton,
                nodes,
                blockRefs: { p1: paragraphElement, c1: componentElement },
            }
        }

        it('maps a focused block element to its node index', () => {
            const { root, componentElement, nodes, blockRefs } = makeBlocks()
            expect(getFocusedBlockCaretPosition(componentElement, root, nodes, blockRefs)).toEqual({ nodeIndex: 1 })
        })

        it('maps focus inside a block (e.g. a button in a query shell) to the block', () => {
            const { root, innerButton, nodes, blockRefs } = makeBlocks()
            expect(getFocusedBlockCaretPosition(innerButton, root, nodes, blockRefs)).toEqual({ nodeIndex: 1 })
        })

        it('returns null for focus outside the notebook or outside any block', () => {
            const { root, nodes, blockRefs } = makeBlocks()
            const outsideElement = document.createElement('div')
            expect(getFocusedBlockCaretPosition(outsideElement, root, nodes, blockRefs)).toBeNull()
            expect(getFocusedBlockCaretPosition(root, root, nodes, blockRefs)).toBeNull()
            expect(getFocusedBlockCaretPosition(null, root, nodes, blockRefs)).toBeNull()
        })
    })
})
