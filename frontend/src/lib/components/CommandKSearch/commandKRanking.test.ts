import { compareRanks, freeWords, highlightSegments, rankCandidate, strictLocalMatches } from './commandKRanking'

const marked = (name: string, words: string[]): string =>
    highlightSegments(name, words)
        .map((segment) => (segment.match ? `[${segment.text}]` : segment.text))
        .join('')

describe('commandKRanking', () => {
    test.each([
        { query: '-name:"old report"', words: [] },
        { query: '!path:"Quarterly reports" revenue', words: ['revenue'] },
        { query: 'name:"old report" rev', words: ['rev'] },
        { query: '-in:x revenue', words: ['revenue'] },
    ])('finds the free words $words in $query', ({ query, words }) => {
        expect(freeWords(query)).toEqual(words)
    })

    it('ranks a pasted wall of text without failing', () => {
        expect(rankCandidate(`experiments ${'x'.repeat(35000)}`, { name: 'Experiments' })).not.toBeNull()
    })

    test.each([
        {
            name: 'Revenue: signup to first paid invoice',
            words: ['rev', 'sign'],
            expected: '[Rev]enue: [sign]up to first paid invoice',
        },
        { name: 'Weekly retention', words: ['retension'], expected: 'Weekly [retention]' },
        { name: 'web-revenue-tracking', words: ['revenue'], expected: 'web-[revenue]-tracking' },
        { name: 'Pageviews', words: [], expected: 'Pageviews' },
    ])('highlights $words in $name', ({ name, words, expected }) => {
        expect(marked(name, words)).toEqual(expected)
    })

    test.each([
        { query: 'metrics', other: 'Data catalog', aliases: ['semantic layer', 'metrics'] },
        { query: 'mertics', other: 'Shared metrics', aliases: [] },
    ])('ranks Metrics above $other for $query', ({ query, other, aliases }) => {
        const metrics = rankCandidate(query, { name: 'Metrics', aliases: ['time series'] }) ?? []
        expect(compareRanks(metrics, rankCandidate(query, { name: other, aliases }) ?? [])).toBeLessThan(0)
    })

    it('matches a plural query to a singular name without a typo', () => {
        expect(strictLocalMatches([{ name: 'Survey' }, { name: 'Surveyed users' }], 'surveys')).toEqual([
            { name: 'Survey' },
        ])
    })

    it('gives a repeated word no proximity bonus', () => {
        const rank = (name: string): number[] => rankCandidate('sign signup', { name }) ?? []
        expect(compareRanks(rank('Sign signup'), rank('Signup'))).toBeLessThan(0)
    })
})
