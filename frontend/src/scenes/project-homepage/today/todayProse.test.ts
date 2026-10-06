import { inlineSegments, renderedText, shortenGitHubLinks } from './todayProse'

describe('todayProse', () => {
    test.each([
        [
            'a bare pull request URL',
            'Fixed in https://github.com/example/web/pull/12, so P2.',
            'Fixed in [#12](https://github.com/example/web/pull/12), so P2.',
        ],
        [
            'a labelled link',
            'See [the PR](https://github.com/example/web/pull/12).',
            'See [the PR](https://github.com/example/web/pull/12).',
        ],
    ])('shortens %s', (_, markdown, expected) => {
        expect(shortenGitHubLinks(markdown)).toEqual(expected)
    })

    test.each([
        ['a valid date', 'Since 2026-08-03.', 'Since 3 Aug.'],
        ['a day past the end of its month, rolled over', 'Since 2026-02-30.', 'Since 2 Mar.'],
        ['a month that does not exist, left as written', 'Since 2026-13-01.', 'Since 2026-13-01.'],
    ])('rewrites %s the way the backend does', (_, markdown, expected) => {
        expect(renderedText(markdown)).toEqual(expected)
    })

    test('splits inline markdown into text, code and links, dropping bold markers', () => {
        expect(
            inlineSegments('Run `retrieve` for **41 teams**, see [#12](https://github.com/example/web/pull/12).')
        ).toEqual([
            { kind: 'text', text: 'Run ' },
            { kind: 'code', text: 'retrieve' },
            { kind: 'text', text: ' for 41 teams, see ' },
            { kind: 'link', text: '#12', href: 'https://github.com/example/web/pull/12' },
            { kind: 'text', text: '.' },
        ])
    })
})
