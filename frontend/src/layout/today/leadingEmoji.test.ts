import { leadingEmoji, withoutLeadingEmoji } from './leadingEmoji'

describe('leadingEmoji', () => {
    it.each([
        ['🎉 PostHog App', '🎉', 'PostHog App'],
        ['🎉PostHog App', '🎉', 'PostHog App'],
        ['👩‍💻 Dev team', '👩‍💻', 'Dev team'],
        ['❤️ Fans', '❤️', 'Fans'],
        ['👍🏽 Thumbs', '👍🏽', 'Thumbs'],
        ['🎉', '🎉', '🎉'],
        ['PostHog 🎉', null, 'PostHog 🎉'],
        ['PostHog', null, 'PostHog'],
        ['', null, ''],
    ])('splits %j into %j and %j', (name, emoji, rest) => {
        expect(leadingEmoji(name)).toEqual(emoji)
        expect(withoutLeadingEmoji(name)).toEqual(rest)
    })
})
