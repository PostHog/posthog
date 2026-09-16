import { MOCK_DEFAULT_BASIC_USER } from 'lib/api.mock'

import { Conversation, ConversationStatus, ConversationType } from '~/types'

import type { Task, TaskAssigneeFilter } from 'products/posthog_ai/frontend/api/types'

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
    it.each<[TaskAssigneeFilter, boolean]>([
        ['for_you', true],
        ['posthog_ai', true],
        ['slack', false],
        ['desktop', false],
        ['my_scouts', false],
        ['team_scouts', false],
        ['all_team', true],
    ])('includes chat history only when it matches %s', (filter, includesChats) => {
        const items = groupAiHistory([conversation], [baseTask], filter).flatMap((group) => group.items)

        expect(items.some((item) => item.kind === 'conversation')).toBe(includesChats)
        expect(items.filter((item) => item.kind === 'task')).toHaveLength(1)
    })

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

    it('shows a chat that has a task as the task once the task list holds it, and as the chat until then', () => {
        // Older than the task rows, so the order below does not depend on same-millisecond timestamps.
        const chatWithTask = {
            ...conversation,
            updated_at: new Date(Date.now() - 2_000).toISOString(),
            task: { id: 'task-id', latest_run: null },
        }
        const otherTask = { ...baseTask, id: 'other-task-id' }

        const withTask = groupAiHistory([chatWithTask], [baseTask]).flatMap((group) => group.items)
        const taskNotLoadedYet = groupAiHistory([chatWithTask], [otherTask]).flatMap((group) => group.items)
        const chatsOnly = groupAiHistory([chatWithTask], []).flatMap((group) => group.items)

        expect(withTask.map((item) => item.key)).toEqual(['task:task-id'])
        expect(taskNotLoadedYet.map((item) => item.key)).toEqual(['task:other-task-id', 'conversation:conversation-id'])
        expect(chatsOnly.map((item) => item.key)).toEqual(['conversation:conversation-id'])
    })
})
