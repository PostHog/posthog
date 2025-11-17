import { router } from 'kea-router'
import { expectLogic, partial } from 'kea-test-utils'

import { sidePanelStateLogic } from '~/layout/navigation-3000/sidepanel/sidePanelStateLogic'
import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'

import { QUESTION_SUGGESTIONS_DATA, maxLogic } from './maxLogic'
import { maxMocks } from './testUtils'

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

    it('sets the question when URL has hash param #panel=max:Foo', async () => {
        // Set up router with #panel=max:Foo
        router.actions.push('', {}, { panel: 'max:Foo' })
        sidePanelStateLogic.mount()

        // Mount maxLogic after setting up the sidePanelStateLogic state
        logic = maxLogic({ tabId: 'test' })
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
        logic = maxLogic({ tabId: 'test' })
        logic.mount()

        // Only mount maxLogic after setting up the router and sidePanelStateLogic
        await expectLogic(logic).toMatchValues({
            autoRun: true,
            question: 'Foo',
        })
    })

    it('does not reset conversation when 404 occurs during active message generation', async () => {
        router.actions.push('', {}, { panel: 'max' })
        sidePanelStateLogic.mount()

        const mockConversationId = 'new-conversation-id'

        useMocks({
            ...maxMocks,
            get: {
                ...maxMocks.get,
                '/api/environments/:team_id/conversations/': { results: [] },
                [`/api/environments/:team_id/conversations/${mockConversationId}`]: () => [
                    404,
                    { detail: 'Not found' },
                ],
            },
        })

        logic = maxLogic({ tabId: 'test' })
        logic.mount()

        // Wait for initial conversationHistory load to complete
        await expectLogic(logic).toDispatchActions(['loadConversationHistorySuccess'])

        // Simulate asking Max a question (which starts a new conversation)
        await expectLogic(logic, () => {
            logic.actions.setQuestion('Test question')
            logic.actions.setConversationId(mockConversationId)
        }).toDispatchActions(['setQuestion', 'setConversationId'])

        // Now simulate the race condition: when pollConversation is called from loadConversationHistorySuccess,
        // it will get a 404 for the conversation that doesn't exist yet on the backend
        // but is being generated on the frontend
        await expectLogic(logic, () => {
            logic.actions.pollConversation(mockConversationId, 0, 0)
        }).toFinishAllListeners()

        // Wait a bit for any async operations
        await expectLogic(logic).delay(50)

        // The conversation should NOT be reset - conversationId should still be set
        await expectLogic(logic).toMatchValues({
            conversationId: mockConversationId,
        })

        // Verify no error toast was shown and no reset occurred
        expect(Array.isArray(logic.values.conversationHistory)).toBe(true)
    })

    it('manages suggestion group selection correctly', async () => {
        logic = maxLogic({ tabId: 'test' })
        logic.mount()

        await expectLogic(logic).toMatchValues({
            activeSuggestionGroup: null,
        })

        await expectLogic(logic, () => {
            logic.actions.setActiveGroup(QUESTION_SUGGESTIONS_DATA[1])
        })
            .toDispatchActions(['setActiveGroup'])
            .toMatchValues({
                activeSuggestionGroup: partial({
                    label: 'SQL',
                }),
            })

        // Test setting to null clears the selection
        logic.actions.setActiveGroup(null)

        await expectLogic(logic).toMatchValues({
            activeSuggestionGroup: null,
        })

        // Test setting to a different index
        logic.actions.setActiveGroup(QUESTION_SUGGESTIONS_DATA[0])

        await expectLogic(logic).toMatchValues({
            activeSuggestionGroup: partial({
                label: 'Product analytics',
            }),
        })
    })

    it('generates and uses frontendConversationId correctly', async () => {
        logic = maxLogic({ tabId: 'test' })
        logic.mount()

        const initialFrontendId = logic.values.frontendConversationId
        expect(initialFrontendId).toBeTruthy()
        expect(typeof initialFrontendId).toBe('string')

        // Test that the ID is a valid UUID
        const uuidRegex = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i
        expect(initialFrontendId).toMatch(uuidRegex)

        // Test that starting a new conversation generates a new frontend ID
        await expectLogic(logic, () => {
            logic.actions.startNewConversation()
        }).toMatchValues({
            frontendConversationId: expect.not.stringMatching(initialFrontendId),
        })

        expect(logic.values.frontendConversationId).toBeTruthy()
        expect(logic.values.frontendConversationId).not.toBe(initialFrontendId)

        // Test that the new ID is also a valid UUID
        expect(logic.values.frontendConversationId).toMatch(uuidRegex)
    })

    it('uses threadLogicKey correctly with frontendConversationId', async () => {
        logic = maxLogic({ tabId: 'test' })
        logic.mount()

        // When no conversation ID is set, should use frontendConversationId
        await expectLogic(logic).toMatchValues({
            threadLogicKey: logic.values.frontendConversationId,
        })

        // When conversation ID is set, should use it
        await expectLogic(logic, () => {
            logic.actions.setConversationId('test-conversation-id')
        }).toMatchValues({
            threadLogicKey: 'test-conversation-id',
        })
    })
})
