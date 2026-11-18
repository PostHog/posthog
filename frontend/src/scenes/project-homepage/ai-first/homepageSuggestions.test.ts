import { FileSystemEntry } from '~/queries/schema/schema-general'
import { Conversation, ConversationStatus, ConversationType } from '~/types'

import type { TaskListItemApi } from 'products/tasks/frontend/generated/api.schemas'

import { ResumableChat, SUGGESTIONS_LIMIT, buildSuggestionItems, pickLastChat } from './homepageSuggestions'

const conversation: Conversation = {
    id: 'conv-1',
    title: 'Retention dip investigation',
    type: ConversationType.Assistant,
    status: ConversationStatus.Idle,
    user: { id: 1 } as Conversation['user'],
    created_at: '2026-01-01T00:00:00Z',
    updated_at: '2026-01-01T00:00:00Z',
}

const webTask = {
    id: 'task-1',
    slug: 'TASK-1',
    title: 'Find semantic layer users',
    origin_product: 'posthog_ai',
    updated_at: '2025-12-01T00:00:00Z',
    last_activity_at: '2026-02-01T00:00:00Z',
} as TaskListItemApi

describe('homepageSuggestions', () => {
    it.each<[string, Conversation[], TaskListItemApi | null, Pick<ResumableChat, 'kind' | 'id'> | null]>([
        // The task row's `updated_at` predates the conversation, so only `last_activity_at` shows it is newer
        ['a task active after the conversation', [conversation], webTask, { kind: 'task', id: 'task-1' }],
        [
            'a conversation updated after the task',
            [{ ...conversation, updated_at: '2026-03-01T00:00:00Z' }],
            webTask,
            { kind: 'conversation', id: 'conv-1' },
        ],
        ['only a task', [], webTask, { kind: 'task', id: 'task-1' }],
        ['a conversation without a title', [{ ...conversation, title: null }], null, null],
        ['a tool-call conversation', [{ ...conversation, type: ConversationType.ToolCall }], null, null],
    ])('picks the last chat from %s', (_case, conversationHistory, latestWebTask, expected) => {
        const lastChat = pickLastChat(conversationHistory, latestWebTask)

        expect(lastChat === null ? null : { kind: lastChat.kind, id: lastChat.id }).toEqual(expected)
    })

    it('orders continue, recents-derived prompts, then static fill', () => {
        const recents: FileSystemEntry[] = [
            { id: '1', path: 'Marketing dashboard', type: 'dashboard' },
            { id: '2', path: 'Signup funnel', type: 'insight/funnels' },
            // Same type as the first entry, so it must not produce a second dashboard prompt
            { id: '3', path: 'Another dashboard', type: 'dashboard' },
            // No prompt template for this type
            { id: '4', path: 'Scratch notebook', type: 'notebook' },
        ]

        const items = buildSuggestionItems(
            { kind: 'conversation', id: 'conv-1', title: 'Retention dip investigation' },
            recents
        )

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
})
