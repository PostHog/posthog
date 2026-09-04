import { isValidElement } from 'react'

import { renderDetailWithLinks } from 'lib/utils/renderDetailWithLinks'

describe('renderDetailWithLinks', () => {
    const linkedUrls = (detail: string): string[] =>
        renderDetailWithLinks(detail)
            .filter((part): part is JSX.Element => isValidElement(part))
            .map((el) => (el.props as { to: string }).to)

    it.each([
        ['links a PostHog docs URL', 'see https://posthog.com/docs/x for help', ['https://posthog.com/docs/x']],
        ['links a PostHog subdomain URL', 'visit https://eu.posthog.com/foo now', ['https://eu.posthog.com/foo']],
        [
            'strips trailing punctuation from the href',
            'read https://posthog.com/docs/x.',
            ['https://posthog.com/docs/x'],
        ],
        [
            'links the production memory-limit docs URL including its fragment',
            'see our docs for more ways to speed it up: https://posthog.com/docs/product-analytics/troubleshooting#how-do-i-speed-up-my-insights-and-queries',
            ['https://posthog.com/docs/product-analytics/troubleshooting#how-do-i-speed-up-my-insights-and-queries'],
        ],
        ['leaves an external URL as plain text', 'go to https://evil.example.com/phish', []],
        ['leaves a lookalike host as plain text', 'open https://posthog.com.evil.com/x here', []],
        ['renders plain detail with no links', 'This query ran out of memory.', []],
    ])('%s', (_name, detail, expected) => {
        expect(linkedUrls(detail)).toEqual(expected)
    })
})
