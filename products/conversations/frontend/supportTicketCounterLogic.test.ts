import { MOCK_DEFAULT_TEAM } from 'lib/api.mock'

import api from 'lib/api'
import { teamLogic } from 'scenes/teamLogic'

import { initKeaTests } from '~/test/init'

import { supportTicketCounterLogic } from './supportTicketCounterLogic'

describe('supportTicketCounterLogic', () => {
    let logic: ReturnType<typeof supportTicketCounterLogic.build>
    let unreadCount: jest.SpyInstance
    const team = { ...MOCK_DEFAULT_TEAM, conversations_enabled: true }

    beforeEach(() => {
        jest.useFakeTimers()
        initKeaTests(true, team)
        unreadCount = jest.spyOn(api.conversationsTickets, 'unreadCount').mockResolvedValue({ count: 3 })
        logic = supportTicketCounterLogic()
        logic.mount()
    })

    afterEach(() => {
        logic.unmount()
        jest.useRealTimers()
        jest.restoreAllMocks()
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
})
