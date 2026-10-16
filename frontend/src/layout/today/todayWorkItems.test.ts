import { dayjs } from 'lib/dayjs'

import { ConversationDetail } from '~/types'

import { TaskListItemApi } from 'products/tasks/frontend/generated/api.schemas'

import { TodayListItemField } from './todayListAppearance'
import {
    DEFAULT_RECENT_FILTERS,
    TodayRecentFilters,
    filterRecentItems,
    recentSourceOptions,
} from './todayRecentFilters'
import { TodayRecentGrouping, TodayRecentSort, groupRecentItems, sortRecentItems } from './todayRecentOrder'
import {
    activeCloudRunId,
    analysisRunId,
    buildRecentItems,
    canHandOff,
    chatItem,
    groupByDay,
    sessionBadges,
    sessionDetails,
    sessionItem,
    shortTimeAgo,
} from './todayWorkItems'

const session = (id: string, lastActivityAt: string, archived = false): TaskListItemApi =>
    ({ id, title: `Session ${id}`, last_activity_at: lastActivityAt, archived }) as TaskListItemApi

const chat = (id: string, updatedAt: string): ConversationDetail =>
    ({ id, title: `Chat ${id}`, updated_at: updatedAt, created_at: updatedAt }) as ConversationDetail

const ME = 7

const mixedItems = [
    sessionItem({
        id: 'mine',
        title: 'Fix Login',
        origin_product: 'user_created',
        created_by: { id: ME },
        latest_run: { environment: 'cloud' },
    } as TaskListItemApi),
    sessionItem({
        id: 'theirs',
        title: 'Triage',
        origin_product: 'error_tracking',
        created_by: { id: 8 },
        latest_run: { environment: 'local' },
    } as TaskListItemApi),
    sessionItem({ id: 'orphan', title: 'Old login', origin_product: 'slack', created_by: null } as TaskListItemApi),
    chatItem({ id: 'chat', title: 'Login funnel', user: { id: ME } } as ConversationDetail),
]

const orderedItems = [
    sessionItem({
        id: 'b',
        title: 'Beta',
        created_at: '2026-03-01T09:00:00',
        last_activity_at: '2026-03-10T09:00:00',
        channel: 'space-1',
        repository: 'PostHog/posthog',
    } as TaskListItemApi),
    sessionItem({
        id: 'a',
        title: 'Alpha',
        created_at: '2026-03-09T09:00:00',
        last_activity_at: '2026-03-09T10:00:00',
        channel: 'deleted-space',
        repository: 'posthog/posthog',
    } as TaskListItemApi),
    chatItem({
        id: 'c',
        title: 'Chat',
        created_at: '2026-03-05T09:00:00',
        updated_at: '2026-03-08T09:00:00',
    } as ConversationDetail),
]

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

    it.each<[string, string, Partial<TodayRecentFilters>, string[]]>([
        ['search ignores case', 'LOGIN', {}, ['mine', 'orphan', 'chat']],
        ['created by me keeps your chats', '', { createdBy: 'me' }, ['mine', 'chat']],
        ['created by others skips a deleted creator', '', { createdBy: 'others' }, ['theirs']],
        ['source matches chats as PostHog AI', '', { sources: ['posthog_ai', 'slack'] }, ['orphan', 'chat']],
        ['search and filters combine', 'login', { createdBy: 'me', sources: ['user_created'] }, ['mine']],
        ['unread keeps unread sessions only', '', { status: 'unread' }, ['theirs']],
        ['pinned only keeps pinned sessions', '', { pinned: 'pinned' }, ['orphan']],
        ['an environment skips chats and sessions that never ran', '', { environment: 'cloud' }, ['mine']],
    ])('filters recent items: %s', (_name, query, filters, ids) => {
        const items = filterRecentItems(
            mixedItems,
            query,
            { ...DEFAULT_RECENT_FILTERS, ...filters },
            {
                userId: ME,
                unreadIds: new Set(['theirs']),
                pinnedIds: new Set(['orphan']),
            }
        )

        expect(items.map((item) => item.id)).toEqual(ids)
    })

    it('offers a selected source that is no longer in the list, so it can be cleared', () => {
        expect(recentSourceOptions(mixedItems, ['review_hog'])).toEqual([
            'error_tracking',
            'posthog_ai',
            'review_hog',
            'slack',
            'user_created',
        ])
    })

    it.each<[TodayRecentSort, TodayRecentGrouping, string[]]>([
        ['recent', 'date', ['Today: b', 'Yesterday: a', 'Sunday: c']],
        ['created', 'date', ['Yesterday: a', 'Thursday: c', 'Mar 1: b']],
        ['alpha', 'date', ['null: a b c']],
        ['recent', 'space', ['Space one: b', 'No space: a c']],
        ['recent', 'repository', ['PostHog/posthog: b a', 'No repository: c']],
    ])('sorts by %s and groups by %s', (sort, grouping, sections) => {
        const now = dayjs('2026-03-10T12:00:00')
        const groups = groupRecentItems(
            sortRecentItems(orderedItems, sort),
            sort,
            grouping,
            { 'space-1': 'Space one' },
            now
        )

        expect(groups.map((group) => `${group.label}: ${group.items.map((item) => item.id).join(' ')}`)).toEqual(
            sections
        )
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

    it.each([
        ['in_progress', 'cloud', 'run-1'],
        ['queued', 'cloud', 'run-1'],
        ['completed', 'cloud', null],
        ['in_progress', 'local', null],
    ])('treats a %s %s run as stoppable: %s', (status, environment, runId) => {
        const item = sessionItem({
            id: 's',
            title: 'Session',
            latest_run: { id: 'run-1', status, environment },
        } as TaskListItemApi)

        expect(activeCloudRunId(item)).toBe(runId)
    })

    it.each<[string, string, string, Record<string, unknown>, Record<string, unknown>, boolean, string[]]>([
        [
            'the Slack source before the pull request',
            'slack',
            'cloud',
            { pr_url: 'https://github.com/a/b/pull/1' },
            {},
            false,
            ['source:slack', 'pullRequest'],
        ],
        ['the source of another product', 'error_tracking', 'cloud', {}, {}, false, ['source:error_tracking']],
        ['nothing for a session someone started', 'user_created', 'cloud', {}, {}, false, []],
        ['Local when nothing else shows', 'user_created', 'local', {}, {}, false, ['local']],
        [
            'only the pull request for a local run that has one',
            'user_created',
            'local',
            { pr_url: 'https://github.com/a/b/pull/1' },
            {},
            false,
            ['pullRequest'],
        ],
        [
            'the live face of someone else working on it, before Local',
            'user_created',
            'local',
            {},
            { created_by: { id: 8, email: 'ada@example.com' }, last_activity_at: '2026-03-10T11:59:00Z' },
            false,
            ['author:live', 'local'],
        ],
        [
            'no face on your own session',
            'user_created',
            'cloud',
            {},
            { created_by: { id: ME, email: 'me@example.com' }, last_activity_at: '2026-03-10T11:59:00Z' },
            false,
            [],
        ],
        [
            'no face once the other person has gone quiet',
            'user_created',
            'cloud',
            {},
            { created_by: { id: 8, email: 'ada@example.com' }, last_activity_at: '2026-03-10T09:00:00Z' },
            false,
            [],
        ],
        [
            'the recent face, without the source when the pin would make four',
            'slack',
            'cloud',
            { pr_url: 'https://github.com/a/b/pull/1' },
            { created_by: { id: 8, email: 'ada@example.com' }, last_activity_at: '2026-03-10T11:00:00Z' },
            true,
            ['author:recent', 'pullRequest'],
        ],
    ])('shows %s as session badges', (_name, origin, environment, output, overrides, pinned, expected) => {
        const item = sessionItem({
            id: 's',
            title: 'Session',
            origin_product: origin,
            latest_run: { environment, output },
            ...overrides,
        } as unknown as TaskListItemApi)

        expect(
            sessionBadges(item, ME, { pinned, now: Date.parse('2026-03-10T12:00:00Z') }).map((badge) =>
                badge.kind === 'source'
                    ? `source:${badge.source}`
                    : badge.kind === 'author'
                      ? `author:${badge.live ? 'live' : 'recent'}`
                      : badge.kind
            )
        ).toEqual(expected)
    })

    it.each([
        ['the closing message, trimmed', { final_message: '  Opened the pull request.\n' }, 'Opened the pull request.'],
        ['nothing when the run saved no message', { pr_url: 'https://github.com/a/b/pull/1' }, null],
        ['nothing for a blank message', { final_message: '   ' }, null],
        ['nothing for a message that is not text', { final_message: { text: 'hi' } }, null],
    ])('reads %s from the latest run', (_name, output, message) => {
        const item = sessionItem({ id: 's', title: 'Session', latest_run: { output } } as unknown as TaskListItemApi)

        expect(item.finalMessage).toBe(message)
    })

    it.each<[string, Partial<TaskListItemApi>, TodayListItemField[], string[]]>([
        [
            'the chosen details in the chosen order',
            {},
            ['creator', 'branch', 'space', 'repository'],
            ['Ada Lovelace', 'fix/retry', 'checkout', 'example-org/web'],
        ],
        ['nothing when no detail is chosen', {}, [], []],
        ['how long ago the session moved', {}, ['activity'], ['2h ago']],
        [
            'just now for a session that moved this minute',
            { last_activity_at: '2026-03-10T12:00:30' },
            ['activity'],
            ['just now'],
        ],
        [
            'only the details the session has',
            { channel: 'deleted-space', repository: null, latest_run: null, created_by: null },
            ['space', 'repository', 'branch', 'creator', 'activity'],
            ['2h ago'],
        ],
    ])('shows %s under a session row', (_name, overrides, fields, expected) => {
        const item = sessionItem({
            id: 's',
            title: 'Session',
            last_activity_at: '2026-03-10T10:00:00',
            channel: 'space-1',
            repository: 'example-org/web',
            latest_run: { branch: 'fix/retry' },
            created_by: { first_name: 'Ada', last_name: 'Lovelace', email: 'ada@example.com' },
            ...overrides,
        } as TaskListItemApi)

        expect(
            sessionDetails(item, fields, { 'space-1': 'checkout' }, dayjs('2026-03-10T12:00:59')).map(
                (detail) => detail.text
            )
        ).toEqual(expected)
    })
})
