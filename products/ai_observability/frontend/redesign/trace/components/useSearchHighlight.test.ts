import { MAX_HIGHLIGHTS, highlightRanges } from './useSearchHighlight'

describe('highlightRanges', () => {
    test.each([
        ['inside one text node', '<p>Where is my invoice?</p>', 'INVOICE', ['invoice']],
        ['across syntax tokens', '<code><span>total</span> = <span>42</span></code>', 'total = 42', ['total = 42']],
        ['up to the cap', `<p>${'a'.repeat(MAX_HIGHLIGHTS + 10)}</p>`, 'a', Array(MAX_HIGHLIGHTS).fill('a')],
    ])('marks matches %s', (_name, html, query, expected) => {
        const container = document.createElement('div')
        container.innerHTML = html

        expect(highlightRanges(container, query).map((range) => range.toString())).toEqual(expected)
    })
})
