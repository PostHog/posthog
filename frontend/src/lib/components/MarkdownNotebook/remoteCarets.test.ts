import { getListItemRefKey } from './listModel'
import { resolveRemoteCaretLayout } from './remoteCarets'
import { NotebookBlockNode } from './types'

describe('remoteCarets', () => {
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

    it('renders block-level carets when no offset is provided (tables)', () => {
        const nodes = [paragraph('p1', 'hello')]
        const element = makeElement('hello', { top: 200, left: 16 })
        const layout = resolveRemoteCaretLayout({ nodeIndex: 0 }, nodes, { p1: element }, {}, container)
        expect(layout).toMatchObject({ top: 200, left: 16 })
    })
})
