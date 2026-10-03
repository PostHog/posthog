import { inlineSegments, shortenGitHubLinks } from './todayProse'

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
