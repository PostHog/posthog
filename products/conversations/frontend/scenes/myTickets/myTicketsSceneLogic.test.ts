import { expectLogic } from 'kea-test-utils'
import posthog from 'posthog-js'

import { initKeaTests } from '~/test/init'

import { sidepanelTicketsLogic } from '../../components/SidePanel/sidepanelTicketsLogic'
import { myTicketsSceneLogic } from './myTicketsSceneLogic'

describe('myTicketsSceneLogic', () => {
    beforeEach(() => {
        initKeaTests()
        ;(posthog as any).conversations = {
            isAvailable: () => true,
            getTickets: jest.fn().mockResolvedValue({ results: [] }),
        }
    })

    afterEach(() => {
        delete (posthog as any).conversations
    })

    // The tickets logic stays mounted for the whole session via the side panel tab icon, so its own
    // boot-time load never re-runs. Without the scene-mount refetch, navigating to /my-tickets shows
    // whatever the boot-time load returned (often nothing) until a full page reload.
    it('refetches tickets when the scene mounts while the tickets logic is already mounted', async () => {
        const ticketsLogic = sidepanelTicketsLogic.build()
        ticketsLogic.mount()
        await expectLogic(ticketsLogic).toFinishAllListeners()

        const getTickets = (posthog as any).conversations.getTickets as jest.Mock
        const callsAtBoot = getTickets.mock.calls.length
        expect(callsAtBoot).toBeGreaterThan(0)

        const sceneLogic = myTicketsSceneLogic.build()
        sceneLogic.mount()
        await expectLogic(ticketsLogic).toFinishAllListeners()

        expect(getTickets.mock.calls.length).toBe(callsAtBoot + 1)

        sceneLogic.unmount()
        ticketsLogic.unmount()
    })
})
