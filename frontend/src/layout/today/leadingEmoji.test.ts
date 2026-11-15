import { leadingEmoji, withoutLeadingEmoji } from './leadingEmoji'

describe('leadingEmoji', () => {
    // A subdivision flag is a black flag plus tag characters that nothing shows on their own.
    const ENGLAND_FLAG = '\u{1F3F4}\u{E0067}\u{E0062}\u{E0065}\u{E006E}\u{E0067}\u{E007F}'

    const CASES: [string, string | null, string][] = [
        ['🎉 PostHog App', '🎉', 'PostHog App'],
        ['🎉PostHog App', '🎉', 'PostHog App'],
        ['👩‍💻 Dev team', '👩‍💻', 'Dev team'],
        ['❤️ Fans', '❤️', 'Fans'],
        ['👍🏽 Thumbs', '👍🏽', 'Thumbs'],
        [`${ENGLAND_FLAG} England`, ENGLAND_FLAG, 'England'],
        ['🎉', '🎉', '🎉'],
        ['PostHog 🎉', null, 'PostHog 🎉'],
        ['PostHog', null, 'PostHog'],
        ['', null, ''],
    ]

    it.each(CASES)('splits %j into %j and %j', (name, emoji, rest) => {
        expect(leadingEmoji(name)).toEqual(emoji)
        expect(withoutLeadingEmoji(name)).toEqual(rest)
    })

    // The top bar imports this module, so a segmenter built at module scope takes the whole app down
    // on a browser that has none, such as Firefox before 125.
    it.each(CASES)('splits %j into %j and %j with no grapheme segmenter', async (name, emoji, rest) => {
        const intl = Intl as { Segmenter?: typeof Intl.Segmenter }
        const segmenter = intl.Segmenter
        try {
            delete intl.Segmenter
            jest.resetModules()
            const withoutSegmenter = await import('./leadingEmoji')

            expect(withoutSegmenter.leadingEmoji(name)).toEqual(emoji)
            expect(withoutSegmenter.withoutLeadingEmoji(name)).toEqual(rest)
        } finally {
            intl.Segmenter = segmenter
            jest.resetModules()
        }
    })
})
