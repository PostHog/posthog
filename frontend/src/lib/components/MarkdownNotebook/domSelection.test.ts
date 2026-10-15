import {
    findTextPosition,
    getSelectedCodeRanges,
    getSelectionRange,
    getTextOffset,
    restoreSelection,
} from './domSelection'
import { NotebookCodeBlockNode } from './types'

function codeNode(language: string, text: string): NotebookCodeBlockNode {
    return { id: 'code-1', type: 'code', language, text }
}

function selectContents(element: HTMLElement): Selection {
    const range = document.createRange()
    range.selectNodeContents(element)
    const selection = window.getSelection() as Selection
    selection.removeAllRanges()
    selection.addRange(range)
    return selection
}

describe('inline selection offsets', () => {
    afterEach(() => {
        window.getSelection()?.removeAllRanges()
        document.body.innerHTML = ''
    })

    it.each([
        ['plain text', 'abcd', 4],
        ['line breaks', 'ab<br>cd<br>ef', 8],
        ['nested marks', '<strong>ab<br><em>cd</em></strong><br><a href="https://example.com">ef</a>', 8],
        ['consecutive and edge breaks', '<br>ab<br><br>cd<br>', 8],
        ['only breaks', '<br><br>', 2],
        ['empty text', '', 0],
    ])('reads and restores every position in %s', (_, html, length) => {
        const element = document.createElement('p')
        element.innerHTML = html
        document.body.appendChild(element)

        expect(getTextOffset(element, element, element.childNodes.length)).toBe(length)
        for (let offset = 0; offset <= length; offset++) {
            const position = findTextPosition(element, offset)
            expect(getTextOffset(element, position.node, position.offset)).toBe(offset)
            restoreSelection(element, offset, length)
            expect(getSelectionRange(element, 'paragraph')).toEqual({ nodeId: 'paragraph', start: offset, end: length })
        }
    })

    it('includes line breaks when a selection extends past the block', () => {
        const element = document.createElement('p')
        element.innerHTML = 'ab<br>cd'
        const next = document.createElement('p')
        next.textContent = 'next'
        document.body.append(element, next)
        const range = document.createRange()
        range.setStart(element.lastChild!, 1)
        range.setEnd(next.firstChild!, 2)
        window.getSelection()!.addRange(range)

        expect(getSelectionRange(element, 'paragraph')).toEqual({ nodeId: 'paragraph', start: 4, end: 5 })
    })
})

describe('getSelectedCodeRanges', () => {
    afterEach(() => {
        window.getSelection()?.removeAllRanges()
        document.body.innerHTML = ''
    })

    it.each([
        {
            label: 'rendered Mermaid preview',
            language: 'mermaid',
            source: 'flowchart LR; A-->B',
            elementText: 'A B',
            expectedRanges: 0,
        },
        {
            label: 'editable JavaScript source',
            language: 'js',
            source: 'const answer = 42',
            elementText: 'const answer = 42',
            expectedRanges: 1,
        },
    ])('$label yields $expectedRanges code range(s)', ({ language, source, elementText, expectedRanges }) => {
        const node = codeNode(language, source)
        const element = document.createElement('div')
        element.textContent = elementText
        document.body.appendChild(element)

        const selection = selectContents(element)

        expect(getSelectedCodeRanges(selection, [node], { 'code-1': element })).toHaveLength(expectedRanges)
    })
})
