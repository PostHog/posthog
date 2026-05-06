import { InAppNotification } from '~/types'

import { buildNotificationSourcePath } from './sidePanelNotificationsLogic'

function makeNotification(overrides: Partial<InAppNotification> = {}): InAppNotification {
    return {
        id: 'test-id',
        team_id: 1,
        notification_type: 'comment_mention',
        priority: 'normal',
        title: 'Test',
        body: '',
        read: false,
        read_at: null,
        resource_type: null,
        source_url: '',
        source_type: null,
        source_id: null,
        created_at: '2026-04-01T00:00:00Z',
        ...overrides,
    }
}

describe('buildNotificationSourcePath', () => {
    it('builds path from source_type and source_id for dashboard', () => {
        const result = buildNotificationSourcePath(
            makeNotification({
                source_type: 'dashboard',
                source_id: '42',
            })
        )
        expect(result).toBe('/dashboard/42')
    })

    it('builds path from source_type and source_id for replay', () => {
        const result = buildNotificationSourcePath(
            makeNotification({
                source_type: 'replay',
                source_id: 'abc-123',
            })
        )
        expect(result).toBe('/replay/abc-123')
    })

    it('builds path from source_type and source_id for feature_flag', () => {
        const result = buildNotificationSourcePath(
            makeNotification({
                source_type: 'feature_flag',
                source_id: '99',
            })
        )
        expect(result).toBe('/feature_flags/99')
    })

    it('builds path from source_type and source_id for insight', () => {
        const result = buildNotificationSourcePath(
            makeNotification({
                source_type: 'insight',
                source_id: 'abc123',
            })
        )
        expect(result).toBe('/insights/abc123')
    })

    it('builds path from source_type and source_id for error_tracking', () => {
        const result = buildNotificationSourcePath(
            makeNotification({
                source_type: 'error_tracking',
                source_id: 'issue-uuid',
            })
        )
        expect(result).toBe('/error_tracking/issue-uuid')
    })

    it('falls back to source_url when source_type is null', () => {
        const result = buildNotificationSourcePath(
            makeNotification({
                source_type: null,
                source_id: null,
                source_url: '/dashboard/legacy',
            })
        )
        expect(result).toBe('/dashboard/legacy')
    })

    it('falls back to source_url when source_type is unrecognized', () => {
        const result = buildNotificationSourcePath(
            makeNotification({
                source_type: 'unknown_type',
                source_id: '123',
                source_url: '/fallback',
            })
        )
        expect(result).toBe('/fallback')
    })

    it('returns null when no source_type and no source_url', () => {
        const result = buildNotificationSourcePath(
            makeNotification({
                source_type: null,
                source_id: null,
                source_url: '',
            })
        )
        expect(result).toBeNull()
    })

    it('returns null when source_type exists but source_id is null', () => {
        const result = buildNotificationSourcePath(
            makeNotification({
                source_type: 'dashboard',
                source_id: null,
                source_url: '',
            })
        )
        expect(result).toBeNull()
    })
})
