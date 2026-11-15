import { ConversationDetail } from '~/types'

import { TaskListItemApi } from 'products/tasks/frontend/generated/api.schemas'

import { chatPreview, sessionPreview } from './todayPreviewCards'
import { chatItem, sessionItem } from './todayWorkItems'

describe('todayPreviewCards', () => {
    it.each<[string, string | null, Record<string, string>, string | null]>([
        ['names the space the session is in', 'space-a', { 'space-a': 'checkout' }, 'checkout'],
        ['leaves out a space the rail has not loaded', 'space-gone', { 'space-a': 'checkout' }, null],
    ])('session card %s', (_name, channel, spaceNames, expected) => {
        const item = sessionItem({
            id: 's',
            title: 'Session',
            channel,
            latest_run: { output: { pr_url: 'https://github.com/example-org/web/pull/7' } },
        } as unknown as TaskListItemApi)
        const preview = sessionPreview(item, {
            unread: false,
            pinned: false,
            pullRequestStates: { 'https://github.com/example-org/web/pull/7': 'merged' },
            spaceNames,
            menuId: 'menu-1',
            userId: null,
        })
        expect([preview.spaceName, preview.pullRequestState]).toEqual([expected, 'merged'])
    })

    it.each<[string, string | null, string | null, string | null, string | null]>([
        ['names a Slack origin and the branch', 'slack', 'feature/checkout', 'Slack', 'feature/checkout'],
        ['leaves out a session a person made by hand', 'user_created', null, null, null],
        ['leaves out a session with no origin', null, '', null, null],
    ])('session card %s', (_name, origin, branch, source, expectedBranch) => {
        const item = sessionItem({
            id: 's',
            title: 'Session',
            origin_product: origin,
            latest_run: { branch },
        } as unknown as TaskListItemApi)
        const preview = sessionPreview(item, {
            unread: false,
            pinned: false,
            pullRequestStates: {},
            spaceNames: {},
            menuId: 'menu-1',
            userId: null,
        })
        expect([preview.source, preview.branch]).toEqual([source, expectedBranch])
    })

    it('names an untitled chat and acts on that chat', () => {
        const item = chatItem({
            id: 'chat-1',
            title: null,
            created_at: '2026-01-01T00:00:00Z',
            updated_at: '2026-01-02T00:00:00Z',
        } as unknown as ConversationDetail)
        expect(chatPreview(item)).toEqual({
            kind: 'chat',
            chatId: 'chat-1',
            title: 'Untitled chat',
            source: 'PostHog AI',
            timestamp: '2026-01-02T00:00:00Z',
        })
    })
})
