import { getSelectedCodeRanges } from './domSelection'
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
