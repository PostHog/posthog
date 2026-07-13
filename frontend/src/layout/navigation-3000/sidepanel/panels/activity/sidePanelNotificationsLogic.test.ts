import { expectLogic } from 'kea-test-utils'

import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'
import { InAppNotification } from '~/types'

import { groupKey, NotificationGroup, sidePanelNotificationsLogic } from './sidePanelNotificationsLogic'

function makeNotification(overrides: Partial<InAppNotification> = {}): InAppNotification {
    return {
        id: 'n1',
        team_id: 1,
        notification_type: 'alert_firing',
        priority: 'normal',
        title: 't',
        body: '',
        resource_type: 'insight',
        resource_id: 'abc',
        source_url: '',
        source_type: null,
        source_id: null,
        metadata: null,
        target_type: 'user',
        target_id: '42',
        created_at: '2026-05-07T12:00:00Z',
        read: false,
        read_at: null,
        ...overrides,
    }
}

describe('groupKey', () => {
    it('combines all dimensions with day bucket', () => {
        const key = groupKey(makeNotification())
        expect(key).toContain('alert_firing')
        expect(key).toContain('user:42')
        expect(key).toContain('insight:abc')
    })

    it('treats missing resource fields as empty', () => {
        const key = groupKey(makeNotification({ resource_type: null, resource_id: '' }))
        expect(key).toContain('|:|')
    })

    it('different notification_type breaks the group', () => {
        const a = makeNotification({ notification_type: 'alert_firing' })
        const b = makeNotification({ notification_type: 'comment_mention' })
        expect(groupKey(a)).not.toEqual(groupKey(b))
    })

    it('different target_id breaks the group', () => {
        const a = makeNotification({ target_id: '42' })
        const b = makeNotification({ target_id: '43' })
        expect(groupKey(a)).not.toEqual(groupKey(b))
    })

    it('different resource_id breaks the group', () => {
        const a = makeNotification({ resource_id: 'abc' })
        const b = makeNotification({ resource_id: 'def' })
        expect(groupKey(a)).not.toEqual(groupKey(b))
    })
})

describe('sidePanelNotificationsLogic.groups selector', () => {
    let logic: ReturnType<typeof sidePanelNotificationsLogic.build>

    beforeEach(() => {
        initKeaTests()
        logic = sidePanelNotificationsLogic()
        logic.mount()
    })

    afterEach(() => {
        logic.unmount()
    })

    it('returns empty array when no notifications', () => {
        expect(logic.values.groups).toEqual([])
    })

    it('groups two events with identical dimensions on the same day', () => {
        const a = makeNotification({ id: 'a', created_at: '2026-05-07T12:00:00Z' })
        const b = makeNotification({ id: 'b', created_at: '2026-05-07T08:00:00Z' })
        logic.actions.setInAppNotifications([a, b], false)
        const groups = logic.values.groups
        expect(groups).toHaveLength(1)
        expect(groups[0].count).toBe(2)
        expect(groups[0].representative.id).toBe('a')
        expect(groups[0].children.map((c: InAppNotification) => c.id)).toEqual(['a', 'b'])
    })

    it('separates events with different group keys', () => {
        const a = makeNotification({ id: 'a', resource_id: 'x' })
        const b = makeNotification({ id: 'b', resource_id: 'y' })
        logic.actions.setInAppNotifications([a, b], false)
        const groups = logic.values.groups
        expect(groups).toHaveLength(2)
        expect(groups.every((g: NotificationGroup) => g.count === 1)).toBe(true)
    })

    it('sets has_unread true if any child unread', () => {
        const a = makeNotification({ id: 'a', read: true })
        const b = makeNotification({ id: 'b', read: false })
        logic.actions.setInAppNotifications([a, b], false)
        expect(logic.values.groups[0].has_unread).toBe(true)
    })

    it('sets has_unread false when every child read', () => {
        const a = makeNotification({ id: 'a', read: true })
        const b = makeNotification({ id: 'b', read: true })
        logic.actions.setInAppNotifications([a, b], false)
        expect(logic.values.groups[0].has_unread).toBe(false)
    })
})

describe('sidePanelNotificationsLogic.loadGroupChildren', () => {
    let logic: ReturnType<typeof sidePanelNotificationsLogic.build>

    beforeEach(() => {
        useMocks({
            get: {
                '/api/projects/:tid/notifications/': () => [
                    200,
                    {
                        results: [makeNotification({ id: 'child-1' }), makeNotification({ id: 'child-2' })],
                        next: null,
                    },
                ],
            },
        })
        initKeaTests()
        logic = sidePanelNotificationsLogic()
        logic.mount()
    })

    afterEach(() => logic.unmount())

    it('marks the group full_children_loaded after fetch', async () => {
        const seed = makeNotification({ id: 'child-1' })
        logic.actions.setInAppNotifications([seed], false)
        await expectLogic(logic, () => {
            logic.actions.loadGroupChildren(logic.values.groups[0])
        }).toDispatchActions(['markGroupChildrenLoaded'])
        expect(logic.values.groups[0].full_children_loaded).toBe(true)
        expect(logic.values.groups[0].count).toBe(2)
    })

    it('toggleGroupExpanded flips state', () => {
        const seed = makeNotification({ id: 'a' })
        logic.actions.setInAppNotifications([seed], false)
        const key = logic.values.groups[0].group_key
        expect(logic.values.expandedGroupKeys.has(key)).toBe(false)
        logic.actions.toggleGroupExpanded(key)
        expect(logic.values.expandedGroupKeys.has(key)).toBe(true)
        logic.actions.toggleGroupExpanded(key)
        expect(logic.values.expandedGroupKeys.has(key)).toBe(false)
    })
})

describe('sidePanelNotificationsLogic.toggleGroupRead', () => {
    let logic: ReturnType<typeof sidePanelNotificationsLogic.build>

    beforeEach(() => {
        useMocks({
            post: {
                '/api/projects/:tid/notifications/mark_read_bulk/': () => [200, { updated: 2 }],
                '/api/projects/:tid/notifications/mark_unread_bulk/': () => [200, { updated: 2 }],
            },
        })
        initKeaTests()
        logic = sidePanelNotificationsLogic()
        logic.mount()
    })

    afterEach(() => logic.unmount())

    it('marks all children read when group has unread', async () => {
        const a = makeNotification({ id: 'a', read: false })
        const b = makeNotification({ id: 'b', read: false })
        logic.actions.setInAppNotifications([a, b], false)
        const key = logic.values.groups[0].group_key
        logic.actions.markGroupChildrenLoaded(key)
        await logic.actions.toggleGroupRead(logic.values.groups[0])
        expect(logic.values.groups[0].has_unread).toBe(false)
    })

    it('marks all children unread when group fully read', async () => {
        const a = makeNotification({ id: 'a', read: true })
        const b = makeNotification({ id: 'b', read: true })
        logic.actions.setInAppNotifications([a, b], false)
        const key = logic.values.groups[0].group_key
        logic.actions.markGroupChildrenLoaded(key)
        await logic.actions.toggleGroupRead(logic.values.groups[0])
        expect(logic.values.groups[0].has_unread).toBe(true)
    })
})

describe('sidePanelNotificationsLogic.mainListOffset', () => {
    let logic: ReturnType<typeof sidePanelNotificationsLogic.build>

    beforeEach(() => {
        initKeaTests()
        logic = sidePanelNotificationsLogic()
        logic.mount()
    })

    afterEach(() => logic.unmount())

    it('resets to notifications.length on setInAppNotifications', () => {
        const seed = Array.from({ length: 20 }, (_, i) => makeNotification({ id: `n${i}` }))
        logic.actions.setInAppNotifications(seed, true)
        expect(logic.values.mainListOffset).toBe(20)
    })

    it('is not bumped by appendInAppNotifications (group-children path)', () => {
        const seed = Array.from({ length: 20 }, (_, i) => makeNotification({ id: `n${i}` }))
        logic.actions.setInAppNotifications(seed, true)
        const children = [makeNotification({ id: 'child-1' }), makeNotification({ id: 'child-2' })]
        logic.actions.appendInAppNotifications(children, true)
        expect(logic.values.mainListOffset).toBe(20)
    })

    it('bumps by the returned page size on loadMoreNotificationsSuccess', () => {
        const seed = Array.from({ length: 20 }, (_, i) => makeNotification({ id: `n${i}` }))
        logic.actions.setInAppNotifications(seed, true)
        logic.actions.loadMoreNotificationsSuccess(20)
        expect(logic.values.mainListOffset).toBe(40)
    })
})

describe('sidePanelNotificationsLogic.manuallyToggledIds', () => {
    let logic: ReturnType<typeof sidePanelNotificationsLogic.build>

    beforeEach(() => {
        useMocks({
            post: {
                '/api/projects/:tid/notifications/:id/mark_read/': () => [200, { status: 'ok' }],
                '/api/projects/:tid/notifications/:id/mark_unread/': () => [200, { status: 'ok' }],
                '/api/projects/:tid/notifications/mark_all_read/': () => [200, { updated: 0 }],
            },
        })
        initKeaTests()
        logic = sidePanelNotificationsLogic()
        logic.mount()
    })

    afterEach(() => logic.unmount())

    // Guards bug fix: without this set, auto-mark-on-view would re-read a notification the user
    // just manually toggled unread.
    it('records ids the user manually toggles so auto-mark can skip them', () => {
        logic.actions.toggleRead('a')
        logic.actions.toggleRead('b')
        expect(logic.values.manuallyToggledIds).toEqual(new Set(['a', 'b']))
    })

    it('clears the set when everything is marked read', () => {
        logic.actions.toggleRead('a')
        logic.actions.markAllAsRead()
        expect(logic.values.manuallyToggledIds.size).toBe(0)
    })
})
