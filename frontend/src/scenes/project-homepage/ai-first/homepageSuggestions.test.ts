import { FileSystemEntry } from '~/queries/schema/schema-general'
import { Conversation, ConversationStatus, ConversationType } from '~/types'

import { SUGGESTIONS_LIMIT, buildSuggestionItems } from './homepageSuggestions'

const conversation: Conversation = {
    id: 'conv-1',
    title: 'Retention dip investigation',
    type: ConversationType.Assistant,
    status: ConversationStatus.Idle,
    user: { id: 1 } as Conversation['user'],
    created_at: '2026-01-01T00:00:00Z',
    updated_at: '2026-01-01T00:00:00Z',
}

describe('buildSuggestionItems', () => {
    it('orders continue, recents-derived prompts, then static fill', () => {
        const recents: FileSystemEntry[] = [
            { id: '1', path: 'Marketing dashboard', type: 'dashboard' },
            { id: '2', path: 'Signup funnel', type: 'insight/funnels' },
            // Same type as the first entry, so it must not produce a second dashboard prompt
            { id: '3', path: 'Another dashboard', type: 'dashboard' },
            // No prompt template for this type
            { id: '4', path: 'Scratch notebook', type: 'notebook' },
        ]

        const items = buildSuggestionItems(conversation, recents)

        expect(items).toHaveLength(SUGGESTIONS_LIMIT)
        expect(items[0]).toMatchObject({ kind: 'suggestion', source: 'continue', conversationId: 'conv-1' })
        expect(items[0].description).toEqual('Retention dip investigation')
        expect(items[1].source).toEqual('recent')
        expect(items[1].prompt).toContain('Marketing dashboard')
        expect(items[1].description).toEqual('Marketing dashboard')
        expect(items[2].source).toEqual('recent')
        expect(items[2].prompt).toContain('Signup funnel')
        expect(items.slice(3).every((item) => item.source === 'static')).toBe(true)
    })

    it('falls back to static prompts alone, all complete and unique', () => {
        const items = buildSuggestionItems(null, [])

        expect(items).toHaveLength(SUGGESTIONS_LIMIT)
        // A fill-in topic suggestion has no complete prompt, so every emitted item must carry one
        expect(items.every((item) => item.source === 'static' && !!item.prompt)).toBe(true)
        expect(new Set(items.map((item) => item.id)).size).toBe(items.length)
    })

    it('skips a conversation without a title', () => {
        const items = buildSuggestionItems({ ...conversation, title: null }, [])

        expect(items.every((item) => item.source === 'static')).toBe(true)
    })
})
