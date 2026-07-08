import { render } from '@testing-library/react'

import { MarkdownTextDiff } from './MarkdownTextDiff'

function getTexts(container: HTMLElement, selector: 'del' | 'ins'): string[] {
    return Array.from(container.querySelectorAll(selector)).map((element) => element.textContent ?? '')
}

describe('MarkdownTextDiff', () => {
    it('renders a pure insert as <ins> only', () => {
        const { container } = render(<MarkdownTextDiff before="abc" after="abcdef" />)
        expect(getTexts(container, 'del')).toEqual([])
        expect(getTexts(container, 'ins').join('')).toEqual('def')
        expect(container.textContent).toEqual('abcdef')
    })

    it('renders a pure delete as <del> only', () => {
        const { container } = render(<MarkdownTextDiff before="abcdef" after="abc" />)
        expect(getTexts(container, 'ins')).toEqual([])
        expect(getTexts(container, 'del').join('')).toEqual('def')
        expect(container.textContent).toEqual('abcdef')
    })

    it('renders a mixed replace as <del> plus <ins>', () => {
        const { container } = render(<MarkdownTextDiff before="the cat sat" after="the car sat" />)
        expect(getTexts(container, 'del').join('')).toEqual('t')
        expect(getTexts(container, 'ins').join('')).toEqual('r')
        expect(container.textContent).toEqual('the catr sat')
    })

    it('renders identical strings without <del> or <ins>', () => {
        const { container } = render(<MarkdownTextDiff before="same text" after="same text" />)
        expect(getTexts(container, 'del')).toEqual([])
        expect(getTexts(container, 'ins')).toEqual([])
        expect(container.textContent).toEqual('same text')
    })

    it('renders an empty before as everything inserted', () => {
        const { container } = render(<MarkdownTextDiff before="" after="brand new" />)
        expect(getTexts(container, 'del')).toEqual([])
        expect(getTexts(container, 'ins')).toEqual(['brand new'])
    })

    it('renders an empty after as everything deleted', () => {
        const { container } = render(<MarkdownTextDiff before="all gone" after="" />)
        expect(getTexts(container, 'ins')).toEqual([])
        expect(getTexts(container, 'del')).toEqual(['all gone'])
    })

    it('keeps whitespace-only insertions visible via pre-wrap', () => {
        const { container } = render(<MarkdownTextDiff before="ab" after="a b" />)
        expect(getTexts(container, 'ins')).toEqual([' '])
        const wrapper = container.firstElementChild as HTMLElement
        expect(wrapper.className).toContain('whitespace-pre-wrap')
    })
})
