import type { ChatMessage } from '../../types'
import { aiDraftAction, aiDraftComposerText } from './aiDraftAction'

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
