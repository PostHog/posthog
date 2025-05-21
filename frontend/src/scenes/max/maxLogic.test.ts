import { router } from 'kea-router'
import { expectLogic } from 'kea-test-utils'

import { sidePanelStateLogic } from '~/layout/navigation-3000/sidepanel/sidePanelStateLogic'
import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'

import { maxMocks, MOCK_CONVERSATION_ID, mockStream } from './__tests__/utils'
import { maxLogic } from './maxLogic'

describe('maxLogic', () => {
    let logic: ReturnType<typeof maxLogic.build>

    beforeEach(() => {
        useMocks(maxMocks)
        initKeaTests()
    })

    afterEach(() => {
        sidePanelStateLogic.unmount()
        logic?.unmount()
    })

    it("doesn't mount sidePanelStateLogic if it's not already mounted", async () => {
        // Mount maxLogic after setting up the sidePanelStateLogic state
        logic = maxLogic()
        logic.mount()

        // Check that sidePanelStateLogic was not mounted
        expect(sidePanelStateLogic.isMounted()).toBe(false)
    })

    it('sets the question when URL has hash param #panel=max:Foo', async () => {
        // Set up router with #panel=max:Foo
        router.actions.push('', {}, { panel: 'max:Foo' })
        sidePanelStateLogic.mount()

        // Mount maxLogic after setting up the sidePanelStateLogic state
        logic = maxLogic()
        logic.mount()

        // Check that the question has been set to "Foo" (via sidePanelStateLogic automatically)
        await expectLogic(logic).toMatchValues({
            question: 'Foo',
        })
    })

    it('sets autoRun and question when URL has hash param #panel=max:!Foo', async () => {
        // Set up router with #panel=max:!Foo
        router.actions.push('', {}, { panel: 'max:!Foo' })
        sidePanelStateLogic.mount()

        // Must create the logic first to spy on its actions
        logic = maxLogic()
        logic.mount()

        // Only mount maxLogic after setting up the router and sidePanelStateLogic
        await expectLogic(logic).toMatchValues({
            autoRun: true,
            question: 'Foo',
        })
    })

    it('resets the thread when a conversation has not been found', async () => {
        router.actions.push('', { chat: MOCK_CONVERSATION_ID }, { panel: 'max' })
        sidePanelStateLogic.mount()

        useMocks({
            ...maxMocks,
            get: {
                ...maxMocks.get,
                [`/api/environments/:team_id/conversations/${MOCK_CONVERSATION_ID}`]: () => [
                    404,
                    { detail: 'Not found' },
                ],
            },
        })

        const streamSpy = mockStream()

        // mount logic
        logic = maxLogic()
        logic.mount()
        await expectLogic(logic).delay(200)
        await expectLogic(logic).toMatchValues({
            conversationId: null,
            conversationHistory: [],
        })
        expect(streamSpy).not.toHaveBeenCalled()
    })
})
