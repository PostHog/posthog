import { MOCK_DEFAULT_TEAM } from 'lib/api.mock'

import { expectLogic } from 'kea-test-utils'

import api from 'lib/api'
import { sceneRenderedLogic } from 'lib/logic/sceneRenderedLogic'
import { onFirstSceneRendered } from 'lib/utils/bootTiming'
import { teamLogic } from 'scenes/teamLogic'

import { initKeaTests } from '~/test/init'

import { supportTicketCounterLogic } from './supportTicketCounterLogic'

jest.mock('lib/utils/bootTiming', () => ({ onFirstSceneRendered: jest.fn() }))

describe('supportTicketCounterLogic', () => {
    let logic: ReturnType<typeof supportTicketCounterLogic.build>
    let unreadCount: jest.SpyInstance
    let renderScene: () => void
    const team = { ...MOCK_DEFAULT_TEAM, conversations_enabled: true }

    beforeEach(() => {
        jest.useFakeTimers()
        jest.mocked(onFirstSceneRendered).mockImplementation((listener) => {
            renderScene = listener
            return () => {}
        })
        initKeaTests(true, team)
        unreadCount = jest.spyOn(api.conversationsTickets, 'unreadCount').mockResolvedValue({ count: 3 })
        logic = supportTicketCounterLogic()
    })

    afterEach(() => {
        logic.unmount()
        jest.useRealTimers()
        jest.restoreAllMocks()
    })

    it.each(['before', 'after'])('loads the count once when it mounts %s the first scene render', async (when) => {
        await expectLogic(logic, () => {
            sceneRenderedLogic.mount()
            if (when === 'after') {
                renderScene()
            }
            logic.mount()
            renderScene()
        })
            .toDispatchActions(['loadUnreadCount'])
            .toNotHaveDispatchedActions(['loadUnreadCount'])
        await jest.advanceTimersByTimeAsync(1)
        expect(unreadCount).toHaveBeenCalledTimes(1)
    })

    it('ignores unrelated team updates but refreshes when support is enabled again', async () => {
        logic.mount()
        renderScene()
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
