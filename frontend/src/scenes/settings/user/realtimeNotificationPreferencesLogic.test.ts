import { expectLogic } from 'kea-test-utils'

import { userLogic } from 'scenes/userLogic'

import { initKeaTests } from '~/test/init'

import { realtimeNotificationPreferencesLogic } from './realtimeNotificationPreferencesLogic'

describe('realtimeNotificationPreferencesLogic', () => {
    let logic: ReturnType<typeof realtimeNotificationPreferencesLogic.build>

    beforeEach(() => {
        initKeaTests()
        userLogic.mount()
        logic = realtimeNotificationPreferencesLogic()
        logic.mount()
    })

    it('isTypeEnabledForTeam: defaults to enabled when no entry stored', async () => {
        userLogic.actions.loadUserSuccess({
            notification_settings: { realtime_notifications_disabled: {} },
        } as any)

        await expectLogic(logic).toMatchValues({
            isTypeEnabledForTeam: expect.any(Function),
        })
        expect(logic.values.isTypeEnabledForTeam('comment_mention', 1)).toBe(true)
    })

    it('isTypeEnabledForTeam: returns false when stored as disabled', async () => {
        userLogic.actions.loadUserSuccess({
            notification_settings: { realtime_notifications_disabled: { comment_mention: { '1': true } } },
        } as any)

        expect(logic.values.isTypeEnabledForTeam('comment_mention', 1)).toBe(false)
    })

    it('projectState: returns "off" when every type for the project is disabled', async () => {
        userLogic.actions.loadUserSuccess({
            active_realtime_notification_types: ['comment_mention', 'alert_firing'],
            notification_settings: {
                realtime_notifications_disabled: {
                    comment_mention: { '1': true },
                    alert_firing: { '1': true },
                },
            },
        } as any)

        expect(logic.values.projectState(1)).toBe('off')
    })

    it('projectState: returns "partial" when some are disabled', async () => {
        userLogic.actions.loadUserSuccess({
            active_realtime_notification_types: ['comment_mention', 'alert_firing'],
            notification_settings: {
                realtime_notifications_disabled: { comment_mention: { '1': true } },
            },
        } as any)

        expect(logic.values.projectState(1)).toBe('partial')
    })

    it('projectState: returns "on" when nothing is disabled', async () => {
        userLogic.actions.loadUserSuccess({
            active_realtime_notification_types: ['comment_mention'],
            notification_settings: { realtime_notifications_disabled: {} },
        } as any)

        expect(logic.values.projectState(1)).toBe('on')
    })
})
