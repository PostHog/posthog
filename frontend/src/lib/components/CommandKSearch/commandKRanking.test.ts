import { compareRanks, highlightSegments, rankLocalItem, strictLocalMatches } from './commandKRanking'

const marked = (name: string, words: string[]): string =>
    highlightSegments(name, words)
        .map((segment) => (segment.match ? `[${segment.text}]` : segment.text))
        .join('')

describe('commandKRanking', () => {
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
        { query: 'recordings', name: 'Session replay', aliases: ['recordings'], alias: 'recordings' },
        { query: 'survey', name: 'Surveys', aliases: ['feedback'], alias: null },
    ])('ranks $name for $query by its best name or alias', ({ query, name, aliases, alias }) => {
        expect(rankLocalItem(query, name, aliases)?.matchedAlias).toEqual(alias)
    })

    it('matches a plural query to a singular name without a typo', () => {
        expect(strictLocalMatches([{ name: 'Survey' }, { name: 'Surveyed users' }], 'surveys')).toEqual([
            { name: 'Survey' },
        ])
    })

    it('gives a repeated word no proximity bonus', () => {
        const rank = (name: string): number[] => rankLocalItem('sign signup', name)?.rank ?? []
        expect(compareRanks(rank('Sign signup'), rank('Signup'))).toBeLessThan(0)
    })
})
