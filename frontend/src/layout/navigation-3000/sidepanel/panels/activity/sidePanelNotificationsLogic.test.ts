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
