import posthog from 'posthog-js'

import { sidePanelNotificationsLogic } from '~/layout/navigation-3000/sidepanel/panels/activity/sidePanelNotificationsLogic'
import { panelLayoutLogic } from '~/layout/panel-layout/panelLayoutLogic'
import { initKeaTests } from '~/test/init'

import { notificationsMenuLogic } from './notificationsMenuLogic'

describe('notificationsMenuLogic', () => {
    let logic: ReturnType<typeof notificationsMenuLogic.build>
    let captureSpy: jest.SpyInstance

    beforeEach(() => {
        initKeaTests()
        captureSpy = jest.spyOn(posthog, 'capture').mockImplementation()
        logic = notificationsMenuLogic()
        logic.mount()
        // panelLayoutLogic persists panel visibility, so each test would otherwise start with
        // whichever panel the previous one left open
        panelLayoutLogic.actions.closePanel()
        captureSpy.mockClear()
    })

    afterEach(() => {
        captureSpy.mockRestore()
        logic.unmount()
    })

    it('toggles the side panel open and closed from the bell', () => {
        logic.actions.toggleNotificationsPanel('bell')
        expect(logic.values.isNotificationsPanelActive).toBe(true)

        // Clicking the bell while the panel is open closes it again, rather than reopening it
        logic.actions.toggleNotificationsPanel('bell')
        expect(logic.values.isNotificationsPanelActive).toBe(false)
    })

    it('reports the unread count the badge was showing when the panel opens', () => {
        sidePanelNotificationsLogic.actions.setInAppUnreadCount(3)

        logic.actions.toggleNotificationsPanel('bell')

        expect(captureSpy).toHaveBeenCalledWith('notification panel opened', {
            source: 'bell',
            unread_count: 3,
            had_unread: true,
        })
    })

    it('attributes an open from a critical toast to the toast, not the bell', () => {
        logic.actions.openToUnread()

        expect(captureSpy).toHaveBeenCalledWith(
            'notification panel opened',
            expect.objectContaining({ source: 'critical_toast' })
        )
        expect(logic.values.activeTab).toEqual('unread')
    })

    it('does not report an open when a critical toast fires with the panel already open', () => {
        logic.actions.toggleNotificationsPanel('bell')
        captureSpy.mockClear()

        logic.actions.openToUnread()

        // The toast still switches to the unread tab, but no panel opened, so nothing to report
        expect(captureSpy).not.toHaveBeenCalled()
        expect(logic.values.activeTab).toEqual('unread')
    })

    it('does not report an open when the bell closes the panel', () => {
        logic.actions.toggleNotificationsPanel('bell')
        captureSpy.mockClear()

        logic.actions.toggleNotificationsPanel('bell')

        expect(captureSpy).not.toHaveBeenCalled()
        expect(panelLayoutLogic.values.isLayoutPanelVisible).toBe(false)
    })
})
