import { conciseText, inlineSegments, shortenGitHubLinks } from './todayProse'

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
        [
            'stops before the limit',
            'First sentence is short. Second sentence is also short. Third one.',
            50,
            'First sentence is short.',
        ],
        [
            'keeps one long sentence',
            'One long sentence that runs past the limit on its own.',
            10,
            'One long sentence that runs past the limit on its own.',
        ],
        [
            'reads list items as sentences',
            '- Reproduce the bug\n- Trace the state',
            60,
            'Reproduce the bug. Trace the state.',
        ],
        [
            'counts a link by the text it shows',
            'Merged in [#12](https://github.com/example/web/pull/12). Land [#13](https://github.com/example/web/pull/13) next.',
            40,
            'Merged in [#12](https://github.com/example/web/pull/12). Land [#13](https://github.com/example/web/pull/13) next.',
        ],
        [
            'closes a bold span it cuts',
            '**The fix is safe. It ships today.** Then measure.',
            20,
            '**The fix is safe.**',
        ],
    ])('keeps text concise when it %s', (_, markdown, maxChars, expected) => {
        expect(conciseText(markdown, maxChars)).toEqual(expected)
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
