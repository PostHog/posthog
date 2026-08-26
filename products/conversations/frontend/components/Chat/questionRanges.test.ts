import { findQuestionRanges } from './questionRanges'

describe('findQuestionRanges', () => {
    function rangeTexts(html: string): string[] {
        const root = document.createElement('div')
        root.innerHTML = html
        return findQuestionRanges(root).map((range) => range.toString())
    }

    test.each([
        ['a question after a statement', '<p>Hello there. Can you help?</p>', ['Can you help?']],
        ['a question spanning inline markup', '<p>Can <strong>you</strong> help?</p>', ['Can you help?']],
        ['two questions in a row', '<p>Why is it slow? Can we fix it?</p>', ['Why is it slow?', 'Can we fix it?']],
        ['a block boundary', '<ul><li>First</li><li>Why?</li></ul>', ['Why?']],
        ['a line break', '<p>First<br>Why?</p>', ['Why?']],
        ['no question at all', '<p>Everything is fine.</p>', []],
        ['a bare question mark', '<p>Fine. ?</p>', []],
    ])('handles %s', (_name, html, expected) => {
        expect(rangeTexts(html)).toEqual(expected)
    })
})
