import { InAppNotification } from '~/types'

import { groupKey } from './sidePanelNotificationsLogic'

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
