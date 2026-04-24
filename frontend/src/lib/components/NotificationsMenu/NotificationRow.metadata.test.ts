import { REALTIME_NOTIFICATION_TYPE_META } from './NotificationRow'

// All values of NotificationType in the backend enum (kept in lockstep manually).
// If a new value is added to the backend enum, update this list AND add a
// corresponding entry to REALTIME_NOTIFICATION_TYPE_META.
const KNOWN_BACKEND_NOTIFICATION_TYPES = [
    'comment_mention',
    'alert_firing',
    'approval_requested',
    'approval_resolved',
    'pipeline_failure',
    'issue_assigned',
] as const

describe('REALTIME_NOTIFICATION_TYPE_META', () => {
    it('has an entry for every known backend NotificationType value', () => {
        for (const type of KNOWN_BACKEND_NOTIFICATION_TYPES) {
            expect(REALTIME_NOTIFICATION_TYPE_META[type]).not.toBeUndefined()
            expect(REALTIME_NOTIFICATION_TYPE_META[type].label).toBeTruthy()
        }
    })
})
