import { MOCK_DEFAULT_BASIC_USER } from 'lib/api.mock'

import { Conversation, ConversationStatus, ConversationType } from '~/types'

import type { Task } from 'products/posthog_ai/frontend/api/types'

import { groupAiHistory, groupConversations } from './NavTabChat'

const conversation: Conversation = {
    id: 'conversation-id',
    status: ConversationStatus.Idle,
    title: 'Testing',
    created_at: new Date().toISOString(),
    updated_at: new Date().toISOString(),
    user: MOCK_DEFAULT_BASIC_USER,
    type: ConversationType.Assistant,
}

describe('groupConversations', () => {
    // A null slipping into conversation history (e.g. from an empty API response body) must not
    // crash the whole chat tab render — skip it and keep the rest of the history usable.
    it('skips null entries instead of throwing', () => {
        const groups = groupConversations([conversation, null as unknown as Conversation])

        // Assert survival of the non-null entry, not the bucket label — the label is incidental
        // to the regression and depends on the wall clock.
        expect(groups.flatMap((group) => group.items)).toEqual([conversation])
    })
})

const baseTask: Task = {
    id: 'task-id',
    task_number: 1,
    slug: 'TASK-1',
    title: 'Fix the checkout funnel',
    description: 'Find the largest conversion drop.',
    origin_product: 'user_created' as Task['origin_product'],
    runtime: 'acp' as Task['runtime'],
    repository: null,
    github_integration: null,
    signal_report: null,
    json_schema: null,
    internal: false,
    latest_run: null,
    created_at: new Date().toISOString(),
    updated_at: new Date().toISOString(),
    created_by: null,
}

describe('groupAiHistory', () => {
    it('combines chats and tasks in updated order', () => {
        const olderConversation = {
            ...conversation,
            updated_at: new Date(Date.now() - 2_000).toISOString(),
        }
        const task: Task = {
            ...baseTask,
            created_at: new Date(Date.now() - 1_000).toISOString(),
            updated_at: new Date(Date.now() - 1_000).toISOString(),
        }

        const items = groupAiHistory([olderConversation], [task]).flatMap((group) => group.items)

        expect(items.map((item) => item.key)).toEqual(['task:task-id', 'conversation:conversation-id'])
        expect(items[0].searchableText).toContain('largest conversion drop')
        // The list is filtered client-side against this text, so a titled task still has to carry
        // the slug the server matches a `TASK-1`-shaped query by.
        expect(items[0].searchableText).toContain('TASK-1')
    })

    // A task row is rarely edited after creation, so `updated_at` stays near its creation time
    // however long its agent runs. Ordering on it buries a task that was active moments ago.
    // `last_activity_at` is nullable for rows written outside the ORM, hence the fallback row.
    it.each([
        ['activity time', new Date(Date.now() - 600_000).toISOString(), new Date(Date.now() - 1_000).toISOString()],
        ['row edit time when there is no activity time', new Date(Date.now() - 1_000).toISOString(), null],
    ])('orders a task by its %s', (_label, updatedAt, lastActivityAt) => {
        const recentConversation = {
            ...conversation,
            updated_at: new Date(Date.now() - 2_000).toISOString(),
        }
        const task: Task = {
            ...baseTask,
            created_at: updatedAt,
            updated_at: updatedAt,
            last_activity_at: lastActivityAt,
        }

        const items = groupAiHistory([recentConversation], [task]).flatMap((group) => group.items)

        expect(items.map((item) => item.key)).toEqual(['task:task-id', 'conversation:conversation-id'])
    })
})
