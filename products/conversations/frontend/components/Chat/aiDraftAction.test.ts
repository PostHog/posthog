import type { ChatMessage } from '../../types'
import { aiDraftAction, aiDraftComposerHtml, aiDraftComposerText } from './aiDraftAction'

describe('aiDraftAction', () => {
    const base: Pick<ChatMessage, 'authorType' | 'isPrivate' | 'persistAs' | 'clarifyingQuestions' | 'content'> = {
        authorType: 'AI',
        isPrivate: true,
        content: 'Try adding the snippet to every page.',
    }

    it.each([
        ['suggested private reply', { persistAs: 'reply' as const }, 'reply'],
        ['legacy private note without persist_as', {}, 'reply'],
        ['private clarifying question', { persistAs: 'clarification' as const }, 'question'],
        [
            'findings with a suggested question',
            { persistAs: 'findings' as const, clarifyingQuestions: ['Which SDK are you using?'] },
            'question',
        ],
        ['findings without a question', { persistAs: 'findings' as const, clarifyingQuestions: [] }, null],
        ['public auto-sent reply', { isPrivate: false, persistAs: 'reply' as const }, null],
        ['public clarifying question', { isPrivate: false, persistAs: 'clarification' as const }, null],
        ['human private note', { authorType: 'human' as const }, null],
    ])('%s', (_name, overrides, expected) => {
        expect(aiDraftAction({ ...base, ...overrides })).toBe(expected)
    })

    // A draft repeats the customer's own words, so an image ref they wrote can reach it. Inserting
    // that into the composer would make the agent's browser fetch whichever host they picked.
    it.each([
        ['a customer-chosen host', 'https://tracker.example.com/pixel.png', 'Screenshot', false],
        ['an intranet host', 'http://10.0.0.5/status.png', '', false],
        ['a PostHog host', 'https://posthog.com/images/docs/sdk.png', 'SDK setup', true],
    ])('keeps a draft image only when the host is ours — %s: %s', (_name, source, alt, kept) => {
        const html = aiDraftComposerHtml({ ...base, content: `Here you go:\n\n![${alt}](${source})` })

        expect(html.includes('<img')).toBe(kept)
        expect(html).toContain(kept ? source : alt || source)
    })

    it('prefills the first clarifying question instead of the findings note', () => {
        expect(
            aiDraftComposerText({
                ...base,
                persistAs: 'findings',
                content: 'Investigation notes\n\nSuggested question for the customer:\n- Which SDK?',
                clarifyingQuestions: ['Which SDK are you using?', 'Which project?'],
            })
        ).toBe('Which SDK are you using?')
    })
})
