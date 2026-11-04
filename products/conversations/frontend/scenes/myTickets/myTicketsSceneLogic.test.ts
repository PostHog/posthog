import { expectLogic } from 'kea-test-utils'
import posthog from 'posthog-js'

import { initKeaTests } from '~/test/init'

import { liveTicketsLogic, sidepanelTicketsLogic } from '../../components/SidePanel/sidepanelTicketsLogic'
import { myTicketsSceneLogic } from './myTicketsSceneLogic'

jest.mock('../../components/SidePanel/ticketsAcrossTabs', () => ({
    loadTicketsAcrossTabs: jest.fn((fetchTickets) => fetchTickets()),
    clearSharedTickets: jest.fn(),
}))

describe('myTicketsSceneLogic', () => {
    beforeEach(() => {
        initKeaTests()
        ;(posthog as any).conversations = {
            isAvailable: () => true,
            getTickets: jest.fn().mockResolvedValue({ results: [] }),
        }
    })

    afterEach(() => {
        jest.restoreAllMocks()
        delete (posthog as any).conversations
    })

    it.each([true, false])('loads tickets when the scene mounts with Support already open=%s', async (supportOpen) => {
        const ticketsLogic = sidepanelTicketsLogic.build()
        ticketsLogic.mount()
        const getTickets = (posthog as any).conversations.getTickets as jest.Mock
        let unmountSupport: (() => void) | undefined
        if (supportOpen) {
            jest.spyOn(console, 'error').mockImplementation(() => {})
            getTickets.mockRejectedValueOnce(new Error('unavailable'))
            unmountSupport = liveTicketsLogic.mount()
            await expectLogic(ticketsLogic).toFinishAllListeners()
            getTickets.mockClear()
        }

        const sceneLogic = myTicketsSceneLogic.build()
        sceneLogic.mount()
        await expectLogic(ticketsLogic).toFinishAllListeners()

        expect(getTickets).toHaveBeenCalledTimes(1)
        expect(liveTicketsLogic.isMounted()).toBe(true)
        sceneLogic.unmount()
        unmountSupport?.()
        ticketsLogic.unmount()
    })
})
