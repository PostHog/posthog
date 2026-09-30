import { dayjs } from 'lib/dayjs'

import { ConversationDetail } from '~/types'

import { TaskListItemApi } from 'products/tasks/frontend/generated/api.schemas'

import { analysisRunId, buildRecentItems, canHandOff, groupByDay, sessionItem, shortTimeAgo } from './todayWorkItems'

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

    it.each([
        ['2026-03-10T11:30:00', '30m'],
        ['2026-03-01T12:00:00', '1w'],
        ['2025-12-01T12:00:00', '3mo'],
        ['2024-03-01T12:00:00', '2y'],
    ])('shortens the age of %s to %s', (timestamp, age) => {
        expect(shortTimeAgo(timestamp, dayjs('2026-03-10T12:00:00'))).toEqual(age)
    })

    it.each([
        [7, true],
        [8, false],
        [undefined, false],
    ])('offers hand off to user %s only when they created the session: %s', (userId, expected) => {
        const item = sessionItem({ id: 's', title: 'Session', created_by: { id: 7 } } as TaskListItemApi)

        expect(canHandOff(item, userId)).toBe(expected)
    })

    it.each([
        ['completed', 'task', 'run-1'],
        ['in_progress', 'task', null],
        ['failed', 'task_analysis', null],
    ])('offers analysis for a %s run of a %s session: %s', (status, originProduct, runId) => {
        const item = sessionItem({
            id: 's',
            title: 'Session',
            origin_product: originProduct,
            latest_run: { id: 'run-1', status },
        } as TaskListItemApi)

        expect(analysisRunId(item)).toBe(runId)
    })
})
