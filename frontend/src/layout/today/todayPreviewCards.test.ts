import { ConversationDetail } from '~/types'

import { ChannelDTOApi, TaskListItemApi, TaskUserBasicInfoApi } from 'products/tasks/frontend/generated/api.schemas'

import { chatPreview, sessionPreview, spaceKind, spacePreview } from './todayPreviewCards'
import { chatItem, sessionItem } from './todayWorkItems'

const person = (uuid: string): TaskUserBasicInfoApi => ({
    id: uuid.length,
    uuid,
    distinct_id: uuid,
    first_name: uuid,
    last_name: '',
    email: `${uuid}@example.com`,
})

const space = (overrides: Partial<ChannelDTOApi>): ChannelDTOApi =>
    ({ id: 'space-a', name: 'checkout', channel_type: 'public', repositories: [], ...overrides }) as ChannelDTOApi

describe('todayPreviewCards', () => {
    it.each<[string, Partial<ChannelDTOApi>, ReturnType<typeof spaceKind>]>([
        [
            'the personal space, whatever its channel type',
            { system_role: 'personal', channel_type: 'public' },
            'personal',
        ],
        ['a private space', { channel_type: 'private', system_role: null }, 'private'],
        ['the general space', { channel_type: 'public', system_role: 'general' }, 'public'],
    ])('names %s', (_name, identity, kind) => {
        expect(spaceKind(space(identity))).toBe(kind)
    })

    it.each<[string, TaskUserBasicInfoApi | null, string[], string[]]>([
        ['leads with a creator who was not active lately', person('ada'), ['grace'], ['ada', 'grace']],
        ['lists a creator who was also active once', person('ada'), ['grace', 'ada'], ['ada', 'grace']],
        ['shows only recent people when the creator is unknown', null, ['grace'], ['grace']],
    ])('space people %s', (_name, creator, recent, expected) => {
        const preview = spacePreview(
            space({ created_by: creator }),
            'checkout',
            { people: recent.map(person), liveUuids: [] },
            undefined
        )
        expect(preview.people.map((p) => p.uuid)).toEqual(expected)
    })

    it('names three repositories and counts the rest', () => {
        const preview = spacePreview(
            space({ repositories: ['a/1', 'a/2', 'a/3', 'a/4', 'a/5'] }),
            'checkout',
            undefined,
            undefined
        )
        expect([preview.repositories, preview.hiddenRepositoryCount]).toEqual([['a/1', 'a/2', 'a/3'], 2])
    })

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
