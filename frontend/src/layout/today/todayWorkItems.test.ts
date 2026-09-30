import { dayjs } from 'lib/dayjs'

import { ConversationDetail } from '~/types'

import { TaskListItemApi } from 'products/tasks/frontend/generated/api.schemas'

import { buildRecentItems, groupByDay } from './todayWorkItems'

const session = (id: string, lastActivityAt: string, archived = false): TaskListItemApi =>
    ({ id, title: `Session ${id}`, last_activity_at: lastActivityAt, archived }) as TaskListItemApi

const chat = (id: string, updatedAt: string): ConversationDetail =>
    ({ id, title: `Chat ${id}`, updated_at: updatedAt, created_at: updatedAt }) as ConversationDetail

describe('todayWorkItems', () => {
    it('merges sessions and chats by latest activity, without pinned or archived sessions', () => {
        const items = buildRecentItems(
            [
                session('s-pinned', '2026-03-10T12:00:00'),
                session('s-old', '2026-03-08T09:00:00'),
                session('s-archived', '2026-03-10T11:00:00', true),
            ],
            [chat('c-new', '2026-03-10T10:00:00')],
            ['s-pinned'],
            10
        )

        expect(items.map((item) => `${item.kind}:${item.id}`)).toEqual(['chat:c-new', 'session:s-old'])
    })

    it.each([
        ['2026-03-10T08:00:00', 'Today'],
        ['2026-03-10T23:00:00', 'Today'],
        ['2026-03-09T08:00:00', 'Yesterday'],
        ['2026-03-06T08:00:00', 'Friday'],
        ['2026-02-20T08:00:00', 'Feb 20'],
        ['2025-12-20T08:00:00', 'Dec 20, 2025'],
    ])('labels an item from %s as %s', (timestamp, label) => {
        const now = dayjs('2026-03-10T12:00:00')
        const groups = groupByDay(buildRecentItems([session('s', timestamp)], [], [], 10), now)

        expect(groups.map((group) => group.label)).toEqual([label])
    })
})
