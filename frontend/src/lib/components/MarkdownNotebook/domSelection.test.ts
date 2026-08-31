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
        // A rendered Mermaid diagram exposes SVG label text, not the fence source, so a code range
        // measured against the element would not map to node.text.
        ['mermaid', 'flowchart LR; A-->B', 'A B', 0],
        ['js', 'const answer = 42', 'const answer = 42', 1],
    ])('language %p over a block yields %p code range(s)', (language, source, elementText, expectedRanges) => {
        const node = codeNode(language, source)
        const element = document.createElement('div')
        element.textContent = elementText
        document.body.appendChild(element)

        const selection = selectContents(element)

        expect(getSelectedCodeRanges(selection, [node], { 'code-1': element })).toHaveLength(expectedRanges)
    })
})
