import { MOCK_DEFAULT_TEAM } from 'lib/api.mock'

import api from 'lib/api'
import { teamLogic } from 'scenes/teamLogic'

import { initKeaTests } from '~/test/init'

import { browserNotificationLogic } from './browserNotificationLogic'
import { supportTicketCounterLogic } from './supportTicketCounterLogic'

describe('supportTicketCounterLogic', () => {
    let logic: ReturnType<typeof supportTicketCounterLogic.build>
    let unreadCount: jest.SpyInstance
    let notificationTitles: string[]
    const team = { ...MOCK_DEFAULT_TEAM, conversations_enabled: true }

    beforeEach(() => {
        jest.useFakeTimers()
        notificationTitles = []
        Object.defineProperty(window, 'Notification', {
            configurable: true,
            writable: true,
            value: class {
                static permission = 'granted'
                close = jest.fn()
                constructor(title: string) {
                    notificationTitles.push(title)
                }
            },
        })
        initKeaTests(true, team)
        unreadCount = jest.spyOn(api.conversationsTickets, 'unreadCount').mockResolvedValue({ count: 3 })
        logic = supportTicketCounterLogic()
        logic.mount()
    })

    afterEach(() => {
        logic.unmount()
        jest.useRealTimers()
        jest.restoreAllMocks()
        delete (window as any).Notification
        localStorage.clear()
    })

    it('ignores unrelated team updates but refreshes when support is enabled again', async () => {
        await jest.advanceTimersByTimeAsync(1)
        teamLogic.actions.loadCurrentTeamSuccess({ ...team, name: 'Updated name' })
        await jest.advanceTimersByTimeAsync(1)
        expect(unreadCount).toHaveBeenCalledTimes(1)
        expect(logic.values.unreadCount).toBe(3)

        teamLogic.actions.loadCurrentTeamSuccess({ ...team, conversations_enabled: false })
        await jest.advanceTimersByTimeAsync(1)
        expect(logic.values.unreadCount).toBe(0)
        await jest.advanceTimersByTimeAsync(60_000)
        expect(unreadCount).toHaveBeenCalledTimes(1)

        teamLogic.actions.loadCurrentTeamSuccess(team)
        await jest.advanceTimersByTimeAsync(1)
        expect(unreadCount).toHaveBeenCalledTimes(2)
    })

    it('notifies only when the count grows after the first load for the team', async () => {
        browserNotificationLogic.actions.setEnabled(true)
        await jest.advanceTimersByTimeAsync(1)
        expect(logic.values.unreadCount).toBe(3)
        expect(notificationTitles).toEqual([])

        unreadCount.mockResolvedValue({ count: 5 })
        await jest.advanceTimersByTimeAsync(5_001)
        expect(logic.values.unreadCount).toBe(5)
        expect(notificationTitles).toEqual(['New support message'])

        teamLogic.actions.loadCurrentTeamSuccess({ ...team, conversations_enabled: false })
        unreadCount.mockResolvedValue({ count: 7 })
        teamLogic.actions.loadCurrentTeamSuccess(team)
        await jest.advanceTimersByTimeAsync(1)
        expect(logic.values.unreadCount).toBe(7)
        expect(notificationTitles).toEqual(['New support message'])

        teamLogic.actions.loadCurrentTeamSuccess({ ...team, conversations_enabled: false })
        unreadCount.mockRejectedValue(new Error('network'))
        teamLogic.actions.loadCurrentTeamSuccess(team)
        await jest.advanceTimersByTimeAsync(1)
        expect(logic.values.unreadCount).toBe(0)

        unreadCount.mockResolvedValue({ count: 9 })
        await jest.advanceTimersByTimeAsync(10_001)
        expect(logic.values.unreadCount).toBe(9)
        expect(notificationTitles).toEqual(['New support message'])
    })
})
